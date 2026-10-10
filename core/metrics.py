import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import case, func
from db.models import CallEventModel, VariantModel, ExperimentModel
from core.router import TrafficRouter
from core.stats import StatisticalEngine

class MetricsCollector:
    """
    Collects, records, and aggregates experimental metrics from the Event Store.
    """

    def __init__(self, db: Session):
        self.db = db

    def record_event(
        self,
        experiment_id: str,
        variant_key: str,
        caller_id: str,
        call_duration_sec: float,
        disposition: str,
        call_id: str = None,
        meeting_fixed: int = None,
        duration_observed: bool = False,
    ) -> CallEventModel:
        if meeting_fixed is None:
            # 1 for meeting booked, 0 otherwise
            meeting_fixed = 1 if disposition.strip().upper() == "MEETING_FIXED" else 0

        event = CallEventModel(
            id=f"evt_{datetime.datetime.utcnow().timestamp()}_{caller_id[-4:]}",
            experiment_id=experiment_id,
            variant_key=variant_key,
            caller_id=caller_id,
            call_id=call_id,
            disposition=disposition,
            call_duration_sec=call_duration_sec,
            meeting_fixed=meeting_fixed,
            duration_observed=duration_observed,
            timestamp=datetime.datetime.utcnow()
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_variant_aggregates(
        self, experiment_id: str, variant_key: str, target_disposition: str
    ) -> Dict[str, Any]:
        """
        Calculates aggregates for a specific variant: total calls, meetings, rate, avg duration.
        """
        normalized_target = target_disposition.strip().casefold()
        res = self.db.query(
            func.count(CallEventModel.id).label("total_calls"),
            func.coalesce(
                func.sum(
                    case(
                        (func.lower(CallEventModel.disposition) == normalized_target, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("goal_successes"),
            func.coalesce(func.avg(case(
                (CallEventModel.duration_observed.is_(True), CallEventModel.call_duration_sec),
                else_=None,
            )), 0.0).label("avg_duration"),
            func.coalesce(func.sum(case((CallEventModel.duration_observed.is_(True), 1), else_=0)), 0).label("duration_samples")
        ).filter(
            CallEventModel.experiment_id == experiment_id,
            CallEventModel.variant_key == variant_key
        ).first()

        total_calls = res.total_calls or 0
        goal_successes = int(res.goal_successes or 0)
        avg_duration = round(float(res.avg_duration or 0.0), 2)
        duration_samples = int(res.duration_samples or 0)
        conversion_rate = round(goal_successes / total_calls, 4) if total_calls > 0 else 0.0
        interval = StatisticalEngine.conversion_credible_interval(goal_successes, total_calls)

        return {
            "variant_key": variant_key,
            "total_calls": total_calls,
            "goal_successes": goal_successes,
            "target_disposition": target_disposition,
            "conversion_rate": conversion_rate,
            "conversion_credible_interval": list(interval),
            "interval_level": 0.95,
            "avg_duration_sec": avg_duration,
            "duration_samples": duration_samples,
        }

    def get_experiment_summary(self, experiment_id: str) -> Dict[str, Any]:
        """
        Returns full live metric breakdown for both variants and split accuracy comparison.
        """
        exp = self.db.query(ExperimentModel).filter(ExperimentModel.id == experiment_id).first()
        if not exp:
            return {"error": "Experiment not found"}

        target_disposition = exp.primary_disposition or "BL Enriched"
        agg_a = self.get_variant_aggregates(experiment_id, "A", target_disposition)
        agg_b = self.get_variant_aggregates(experiment_id, "B", target_disposition)

        # Find configured B weight
        b_variant = self.db.query(VariantModel).filter(
            VariantModel.experiment_id == experiment_id,
            VariantModel.key == "B"
        ).first()
        configured_b_weight = b_variant.traffic_weight if b_variant else 0.10
        a_variant = self.db.query(VariantModel).filter(
            VariantModel.experiment_id == experiment_id,
            VariantModel.key == "A"
        ).first()

        split_audit = TrafficRouter.audit_split_accuracy(
            total_calls_a=agg_a["total_calls"],
            total_calls_b=agg_b["total_calls"],
            configured_b_weight=configured_b_weight
        )

        # Primary metric lift (absolute & relative)
        rate_a = agg_a["conversion_rate"]
        rate_b = agg_b["conversion_rate"]
        abs_lift = round(rate_b - rate_a, 4)
        rel_lift = round(((rate_b - rate_a) / rate_a) * 100, 2) if rate_a > 0 else 0.0

        # Secondary metric delta (duration)
        duration_available = agg_a["duration_samples"] > 0 and agg_b["duration_samples"] > 0
        dur_delta = round(agg_b["avg_duration_sec"] - agg_a["avg_duration_sec"], 2) if duration_available else None
        guardrail_safe = (dur_delta <= exp.guardrail_max_delta) if duration_available else None
        posterior_b_wins = StatisticalEngine.compute_bayesian_win_probability(
            agg_a["goal_successes"], agg_a["total_calls"],
            agg_b["goal_successes"], agg_b["total_calls"],
        )
        started_at = exp.started_at or exp.created_at
        window_ended = (datetime.datetime.utcnow() - started_at).total_seconds() >= exp.window_hours * 3600
        min_sample_met = (agg_a["total_calls"] >= exp.min_sample_per_variant and
                          agg_b["total_calls"] >= exp.min_sample_per_variant)
        early_n = max(5, int(exp.min_sample_per_variant * 0.25))
        early_sample_met = agg_a["total_calls"] >= early_n and agg_b["total_calls"] >= early_n
        if exp.status != "RUNNING":
            decision_preview = f"{exp.status} — Variant {exp.deployed_variant_key or 'A'} deployed"
        elif early_sample_met and posterior_b_wins <= exp.early_stop_threshold:
            decision_preview = "EARLY STOP ELIGIBLE — challenger appears harmful"
        elif early_sample_met and duration_available and not guardrail_safe:
            decision_preview = "EARLY STOP ELIGIBLE — duration guardrail breached"
        elif window_ended and min_sample_met and posterior_b_wins >= exp.confidence_level and guardrail_safe:
            decision_preview = "PROMOTION ELIGIBLE — awaiting decision evaluator"
        elif window_ended and min_sample_met and posterior_b_wins >= exp.confidence_level and not duration_available:
            decision_preview = "INCONCLUSIVE — duration guardrail data unavailable"
        elif window_ended:
            decision_preview = "INCONCLUSIVE — window ended without sufficient evidence"
        elif min_sample_met and posterior_b_wins >= exp.confidence_level:
            decision_preview = "EVIDENCE THRESHOLD MET — waiting for window end"
        else:
            decision_preview = "CONTINUE TESTING — collecting evidence"

        return {
            "experiment_id": experiment_id,
            "status": exp.status,
            "window_hours": exp.window_hours,
            "started_at": exp.started_at.isoformat() if exp.started_at else None,
            "deployed_variant": exp.deployed_variant_key or "A",
            "min_sample_per_variant": exp.min_sample_per_variant,
            "confidence_level": exp.confidence_level,
            "current_decision": decision_preview,
            "posterior_probability_b_wins": posterior_b_wins,
            "primary_goal": target_disposition,
            "metrics": {
                "variant_A": agg_a,
                "variant_B": agg_b,
                "lift": {
                    "absolute_lift": abs_lift,
                    "relative_lift_pct": rel_lift,
                },
                "guardrail": {
                    "duration_delta_sec": dur_delta,
                    "max_allowed_delta": exp.guardrail_max_delta,
                    "is_safe": guardrail_safe,
                    "available": duration_available,
                    "samples_a": agg_a["duration_samples"],
                    "samples_b": agg_b["duration_samples"],
                }
            },
            "traffic_split_audit": split_audit,
            "configured_traffic": {
                "A": a_variant.traffic_weight if a_variant else 0.0,
                "B": configured_b_weight,
            }
        }
