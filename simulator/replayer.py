import csv
import asyncio
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from core.router import TrafficRouter
from core.metrics import MetricsCollector
from db.repository import ExperimentRepository
from simulator.sarvam_client import SarvamVoiceAgentClient

class CSVReplaySimulator:
    """
    Simulates traffic replay by consuming historical call records from CSV,
    routing callers through the deterministic hash router, applying prompt variants,
    and recording outcomes into the Event Store.
    """

    def __init__(self, db: Session, sarvam_client: Optional[SarvamVoiceAgentClient] = None):
        self.db = db
        self.repo = ExperimentRepository(db)
        self.collector = MetricsCollector(db)
        self.sarvam = sarvam_client or SarvamVoiceAgentClient()

    def load_historical_calls(self, csv_filepath: str) -> List[Dict[str, Any]]:
        calls = []
        with open(csv_filepath, mode="r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                duration = row.get("call_duration_sec") or "60"
                calls.append({
                    "call_id": row.get("call_id"),
                    "caller_id": str(row.get("caller_id")),
                    "call_duration_sec": float(duration),
                    "disposition": row.get("disposition", "NO_ANSWER"),
                    "meeting_fixed": int(row.get("meeting_fixed") or 0),
                })
        return calls

    async def replay_call(
        self,
        call_data: Dict[str, Any],
        experiment_id: str,
        b_traffic_weight: float = 0.10,
        variant_b_lift: float = 0.20
    ) -> Dict[str, Any]:
        """
        Replays an individual call:
          1. Deterministically routes the caller to Variant A or Variant B.
          2. Evaluates the outcome (using historical baseline or variant lift model).
          3. Persists the event in the database.
        """
        caller_id = call_data["caller_id"]
        variant_key, bucket = TrafficRouter.assign_variant(caller_id, experiment_id, b_traffic_weight)

        disposition = call_data["disposition"]
        duration = call_data["call_duration_sec"]
        # Prefer the normalized outcome flag from the IndiaMART parser.  The
        # raw disposition is retained for reporting and need not be renamed.
        meeting_fixed = int(call_data.get("meeting_fixed", 0))

        # Lift simulation for Variant B (simulating Challenger prompt)
        if variant_key == "B":
            # For demonstration, B has a positive lift factor
            if meeting_fixed == 0 and (bucket * 100) % 3 == 0:
                meeting_fixed = 1
                disposition = "MEETING_FIXED"
                duration += 12.0 # Slight duration impact
        
        event = self.collector.record_event(
            experiment_id=experiment_id,
            variant_key=variant_key,
            caller_id=caller_id,
            call_duration_sec=duration,
            disposition=disposition,
            call_id=call_data.get("call_id"),
            meeting_fixed=meeting_fixed
        )

        return {
            "event_id": event.id,
            "experiment_id": experiment_id,
            "caller_id": caller_id,
            "assigned_variant": variant_key,
            "bucket": bucket,
            "disposition": disposition,
            "duration_sec": duration,
            "meeting_fixed": meeting_fixed
        }

    async def replay_batch(
        self,
        csv_filepath: str,
        experiment_id: str,
        b_traffic_weight: float = 0.10,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        calls = self.load_historical_calls(csv_filepath)
        if limit:
            calls = calls[:limit]
        
        results = []
        for call in calls:
            res = await self.replay_call(call, experiment_id, b_traffic_weight)
            results.append(res)
        return results
