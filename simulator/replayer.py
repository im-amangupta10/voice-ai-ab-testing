import csv
import datetime
import hashlib
from typing import List, Dict, Any, Optional, Callable
from sqlalchemy.orm import Session
from core.router import TrafficRouter
from core.metrics import MetricsCollector
from db.repository import ExperimentRepository
from simulator.sarvam_client import SarvamVoiceAgentClient

class CSVReplaySimulator:
    """
    Replays recorded buyer scenarios through A/B prompts using Sarvam STT + Chat.
    """

    def __init__(self, db: Session, sarvam_client: Optional[SarvamVoiceAgentClient] = None):
        self.db = db
        self.repo = ExperimentRepository(db)
        self.collector = MetricsCollector(db)
        # Keep the dashboard demo responsive; failures flow into the explicitly labeled CSV fallback.
        self.sarvam = sarvam_client or SarvamVoiceAgentClient(timeout_sec=20.0)

    def load_historical_calls(self, csv_filepath: str) -> List[Dict[str, Any]]:
        calls = []
        with open(csv_filepath, mode="r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                duration = row.get("call_duration_sec") or "0"
                calls.append({
                    "call_id": row.get("call_id"),
                    "caller_id": str(row.get("caller_id")),
                    "call_duration_sec": float(duration),
                    "call_duration_observed": str(row.get("call_duration_observed", "0")).strip().lower() in {"1", "true", "yes"},
                    "disposition": row.get("disposition", "NO_ANSWER"),
                    "meeting_fixed": int(row.get("meeting_fixed") or 0),
                    "recording_url": row.get("recording_url", ""),
                })
        return calls

    async def replay_call(
        self,
        call_data: Dict[str, Any],
        experiment_id: str,
        b_traffic_weight: float = 0.10,
        fallback_to_historical: bool = True,
    ) -> Dict[str, Any]:
        """
        Uses Sarvam to estimate an outcome from a recording when available. If that
        path fails and fallback is enabled, persists the CSV label with an explicit
        historical_csv_fallback marker; that label is not Sarvam-generated.
        """
        caller_id = call_data["caller_id"]
        experiment = self.repo.get_experiment(experiment_id)
        if not experiment:
            return {"status": "error", "call_id": call_data.get("call_id"), "error_message": "Experiment not found."}
        if experiment.status == "RUNNING":
            started_at = experiment.started_at or experiment.created_at
            if (datetime.datetime.utcnow() - started_at).total_seconds() >= experiment.window_hours * 3600:
                from core.decision import DecisionEngine
                DecisionEngine(self.db).evaluate_experiment(experiment_id)
                experiment = self.repo.get_experiment(experiment_id)
        if experiment.status != "RUNNING":
            effective_variant = experiment.deployed_variant_key or "A"
            return {"status": "routed", "call_id": call_data.get("call_id"),
                    "assigned_variant": effective_variant,
                    "message": f"Experiment is {experiment.status}; traffic routes to deployed Variant {effective_variant}."}
        call_id = str(call_data.get("call_id") or "")
        if call_id and self.repo.get_event_by_call_id(experiment_id, call_id):
            return {"status": "skipped", "call_id": call_id, "error_message": "Call already replayed for this experiment."}
        b_variant = next((item for item in experiment.variants if item.key == "B"), None)
        if experiment.status == "RUNNING":
            configured_b_weight = b_variant.traffic_weight if b_variant else 0.0
            variant_key, bucket = TrafficRouter.assign_variant(caller_id, experiment_id, configured_b_weight)
        else:
            # A paused/stopped test sends traffic to control; a winner routes to its deployed variant.
            variant_key = experiment.deployed_variant_key or "A"
            bucket = TrafficRouter.get_bucket(caller_id, experiment_id)
        variant = next((item for item in experiment.variants if item.key == variant_key), None) if experiment else None
        if not experiment or not variant:
            return {"status": "error", "call_id": call_data.get("call_id"), "assigned_variant": variant_key,
                    "error_message": "Experiment/variant not found; call was not counted."}
        agent_prompt = variant.content
        if variant.variant_type == "DELTA_PATCH":
            agent_prompt = f"{experiment.base_prompt}\n\nCHALLENGER INSTRUCTIONS:\n{variant.content}"
        fallback_reason = None
        stt_result = {"status": "error", "error_message": "SARVAM_API_KEY is not configured."}
        if self.sarvam.is_configured:
            stt_result = await self.sarvam.transcribe_recording(call_data.get("recording_url", ""))
        sarvam_result = None
        if stt_result.get("status") != "success":
            fallback_reason = stt_result.get("error_message", "Recording transcription failed.")
        else:
            labels = [experiment.primary_disposition] if experiment.primary_disposition else []
            sarvam_result = await self.sarvam.simulate_prompt_variant(
                transcript=stt_result["transcript"], agent_prompt=agent_prompt, allowed_dispositions=labels
            )
            if sarvam_result.get("status") != "success":
                fallback_reason = sarvam_result.get("error_message", "Sarvam disposition evaluation failed.")

        if fallback_reason:
            if not fallback_to_historical:
                return {"status": "error", "call_id": call_data.get("call_id"), "assigned_variant": variant_key,
                        "error_message": fallback_reason}
            # Historical labels keep the demo usable but are explicitly not Sarvam-generated outcomes.
            disposition = str(call_data.get("disposition") or "No Information").strip()
            duration = call_data["call_duration_sec"]
            meeting_fixed = int(disposition in {"BL Enriched", "BL Approved", "BL Generated"})
            event = self.collector.record_event(
                experiment_id=experiment_id, variant_key=variant_key, caller_id=caller_id,
                call_duration_sec=duration, disposition=disposition, call_id=call_id,
                meeting_fixed=meeting_fixed, duration_observed=call_data.get("call_duration_observed", False),
            )
            return {"status": "success", "event_id": event.id, "call_id": call_id,
                    "assigned_variant": variant_key, "disposition": disposition,
                    "duration_sec": duration, "evaluation_mode": "historical_csv_fallback",
                    "fallback_reason": fallback_reason}

        disposition = sarvam_result["disposition"]
        duration = call_data["call_duration_sec"]
        meeting_fixed = int(disposition in {"BL Enriched", "BL Approved", "BL Generated"})
        
        event = self.collector.record_event(
            experiment_id=experiment_id,
            variant_key=variant_key,
            caller_id=caller_id,
            call_duration_sec=duration,
            disposition=disposition,
            call_id=call_data.get("call_id"),
            meeting_fixed=meeting_fixed,
            duration_observed=call_data.get("call_duration_observed", False),
        )

        return {
            "status": "success",
            "event_id": event.id,
            "experiment_id": experiment_id,
            "caller_id": caller_id,
            "assigned_variant": variant_key,
            "bucket": bucket,
            "disposition": disposition,
            "duration_sec": duration,
            "meeting_fixed": meeting_fixed,
            "evaluation_mode": "simulated_counterfactual",
            "transcript": stt_result["transcript"],
            "sarvam": {"status": sarvam_result.get("status"),
                       "confidence": sarvam_result.get("confidence"),
                       "evidence": sarvam_result.get("evidence"),
                       "summary": sarvam_result.get("summary"),
                       "simulated_exchange": sarvam_result.get("simulated_exchange"),
                       "stt_request_id": stt_result.get("request_id"),
                       "chat_request_id": sarvam_result.get("request_id")}
        }

    async def replay_batch(
        self,
        csv_filepath: str,
        experiment_id: str,
        b_traffic_weight: float = 0.10,
        limit: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        calls = self.load_historical_calls(csv_filepath)
        # Process each CSV row once per experiment; later runs continue with fresh rows.
        calls = [row for row in calls if not (
            row.get("call_id") and self.repo.get_event_by_call_id(experiment_id, str(row["call_id"]))
        )]
        if limit:
            calls = sorted(calls, key=lambda row: hashlib.sha256(
                f"{experiment_id}:{row.get('call_id')}".encode("utf-8")).hexdigest())[:limit]
        
        results = []
        total = len(calls)
        for call in calls:
            res = await self.replay_call(call, experiment_id, b_traffic_weight)
            results.append(res)
            if progress_callback:
                progress_callback(len(results), total, res)
        return results
