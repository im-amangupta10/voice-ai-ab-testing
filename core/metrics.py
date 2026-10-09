import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.models import CallEventModel, VariantModel, ExperimentModel
from core.router import TrafficRouter

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
        meeting_fixed: int = None
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
            timestamp=datetime.datetime.utcnow()
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_variant_aggregates(self, experiment_id: str, variant_key: str) -> Dict[str, Any]:
        """
        Calculates aggregates for a specific variant: total calls, meetings, rate, avg duration.
        """
        res = self.db.query(
            func.count(CallEventModel.id).label("total_calls"),
            func.coalesce(func.sum(CallEventModel.meeting_fixed), 0).label("meetings_fixed"),
            func.coalesce(func.avg(CallEventModel.call_duration_sec), 0.0).label("avg_duration")
        ).filter(
            CallEventModel.experiment_id == experiment_id,
            CallEventModel.variant_key == variant_key
        ).first()

        total_calls = res.total_calls or 0
        meetings_fixed = int(res.meetings_fixed or 0)
        avg_duration = round(float(res.avg_duration or 0.0), 2)
        conversion_rate = round(meetings_fixed / total_calls, 4) if total_calls > 0 else 0.0

        return {
            "variant_key": variant_key,
            "total_calls": total_calls,
            "meetings_fixed": meetings_fixed,
            "conversion_rate": conversion_rate,
            "avg_duration_sec": avg_duration
        }

    def get_experiment_summary(self, experiment_id: str) -> Dict[str, Any]:
        """
        Returns full live metric breakdown for both variants and split accuracy comparison.
        """
        exp = self.db.query(ExperimentModel).filter(ExperimentModel.id == experiment_id).first()
        if not exp:
            return {"error": "Experiment not found"}

        agg_a = self.get_variant_aggregates(experiment_id, "A")
        agg_b = self.get_variant_aggregates(experiment_id, "B")

        # Find configured B weight
        b_variant = self.db.query(VariantModel).filter(
            VariantModel.experiment_id == experiment_id,
            VariantModel.key == "B"
        ).first()
        configured_b_weight = b_variant.traffic_weight if b_variant else 0.10

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
        dur_delta = round(agg_b["avg_duration_sec"] - agg_a["avg_duration_sec"], 2)
        guardrail_safe = dur_delta <= exp.guardrail_max_delta

        return {
            "experiment_id": experiment_id,
            "status": exp.status,
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
                    "is_safe": guardrail_safe
                }
            },
            "traffic_split_audit": split_audit
        }
