import json
import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from db.models import ExperimentModel, VariantModel, CallEventModel, AuditLogModel, ExperimentStatus

class ExperimentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_experiment(
        self,
        exp_id: str,
        name: str,
        base_prompt: str,
        variants_data: List[Dict[str, Any]],
        description: Optional[str] = None,
        window_hours: int = 48,
        min_sample_per_variant: int = 100,
        confidence_level: float = 0.95,
        primary_metric: str = "meeting_fixed_rate",
        primary_disposition: str = "BL Enriched",
        secondary_metric: str = "avg_call_duration_sec",
        guardrail_max_delta: float = 30.0,
        early_stop_threshold: float = 0.01,
    ) -> ExperimentModel:
        exp = ExperimentModel(
            id=exp_id,
            name=name,
            description=description,
            status=ExperimentStatus.DRAFT.value,
            base_prompt=base_prompt,
            window_hours=window_hours,
            min_sample_per_variant=min_sample_per_variant,
            confidence_level=confidence_level,
            primary_metric=primary_metric,
            primary_disposition=primary_disposition,
            secondary_metric=secondary_metric,
            guardrail_max_delta=guardrail_max_delta,
            early_stop_threshold=early_stop_threshold,
        )
        self.db.add(exp)
        
        for v in variants_data:
            variant = VariantModel(
                id=v.get("id", f"{exp_id}_{v['key']}"),
                experiment_id=exp_id,
                key=v["key"],
                name=v["name"],
                variant_type=v.get("variant_type", "FULL_PROMPT"),
                content=v["content"],
                traffic_weight=v["traffic_weight"],
            )
            self.db.add(variant)

        self.add_audit_log(exp_id, "CREATED", {"config": {
            "name": name,
            "variants": [v["key"] for v in variants_data],
            "primary_disposition": primary_disposition,
        }})
        self.db.commit()
        self.db.refresh(exp)
        return exp

    def get_experiment(self, exp_id: str) -> Optional[ExperimentModel]:
        return self.db.query(ExperimentModel).filter(ExperimentModel.id == exp_id).first()

    def list_experiments(self) -> List[ExperimentModel]:
        return self.db.query(ExperimentModel).order_by(ExperimentModel.created_at.desc()).all()

    def update_status(self, exp_id: str, new_status: ExperimentStatus, reason: Optional[str] = None,
                      promoted_variant_key: Optional[str] = None,
                      decision_evidence: Optional[Dict[str, Any]] = None) -> Optional[ExperimentModel]:
        exp = self.get_experiment(exp_id)
        if not exp:
            return None
        
        old_status = exp.status
        exp.status = new_status.value
        if new_status == ExperimentStatus.RUNNING and exp.started_at is None:
            exp.started_at = datetime.datetime.utcnow()
        if promoted_variant_key is not None:
            exp.deployed_variant_key = promoted_variant_key
        if new_status in [ExperimentStatus.CONCLUDED, ExperimentStatus.STOPPED_EARLY]:
            exp.concluded_at = datetime.datetime.utcnow()

        self.add_audit_log(
            exp_id, 
            f"STATUS_CHANGE_{new_status.value}", 
            {"old_status": old_status, "new_status": new_status.value, "reason": reason,
             "evidence": decision_evidence}
        )
        self.db.commit()
        self.db.refresh(exp)
        return exp

    def add_audit_log(self, exp_id: str, action: str, details: Optional[Dict[str, Any]] = None):
        details_str = json.dumps(details) if details else None
        log = AuditLogModel(
            id=f"log_{datetime.datetime.utcnow().timestamp()}_{action}",
            experiment_id=exp_id,
            action=action,
            details=details_str,
        )
        self.db.add(log)

    def record_call_event(
        self,
        event_id: str,
        experiment_id: str,
        variant_key: str,
        caller_id: str,
        call_duration_sec: float,
        disposition: str,
        call_id: Optional[str] = None,
        meeting_fixed: Optional[int] = None
    ) -> CallEventModel:
        if meeting_fixed is None:
            meeting_fixed = 1 if disposition.upper() == "MEETING_FIXED" else 0

        event = CallEventModel(
            id=event_id,
            experiment_id=experiment_id,
            variant_key=variant_key,
            caller_id=caller_id,
            call_id=call_id,
            disposition=disposition,
            call_duration_sec=call_duration_sec,
            meeting_fixed=meeting_fixed,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_events(self, experiment_id: str, variant_key: Optional[str] = None) -> List[CallEventModel]:
        query = self.db.query(CallEventModel).filter(CallEventModel.experiment_id == experiment_id)
        if variant_key:
            query = query.filter(CallEventModel.variant_key == variant_key)
        return query.order_by(CallEventModel.timestamp.asc()).all()

    def get_event_by_call_id(self, experiment_id: str, call_id: str) -> Optional[CallEventModel]:
        return self.db.query(CallEventModel).filter(
            CallEventModel.experiment_id == experiment_id,
            CallEventModel.call_id == call_id,
        ).first()
