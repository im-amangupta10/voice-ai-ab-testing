import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from db.connection import get_db
from db.repository import ExperimentRepository
from db.models import ExperimentStatus
from core.experiment import (
    ExperimentCreate,
    ExperimentResponse,
    ExperimentStatusUpdate
)
from core.metrics import MetricsCollector
from core.decision import DecisionEngine
from core.prompts import generate_challenger_prompt

router = APIRouter(prefix="/experiments", tags=["Experiments"])

@router.post("", response_model=ExperimentResponse, status_code=status.HTTP_201_CREATED)
def create_experiment(payload: ExperimentCreate, db: Session = Depends(get_db)):
    repo = ExperimentRepository(db)
    exp_id = payload.id or f"exp_{uuid.uuid4().hex[:8]}"

    existing = repo.get_experiment(exp_id)
    if existing:
        raise HTTPException(status_code=400, detail=f"Experiment with ID '{exp_id}' already exists.")

    variants_data = [v.model_dump() for v in payload.variants]
    variant_keys = {variant["key"].upper() for variant in variants_data}
    if "B" not in variant_keys:
        variants_data.append({
            "key": "B",
            "name": "Challenger (generated)",
            "variant_type": "FULL_PROMPT",
            "content": generate_challenger_prompt(payload.base_prompt, seed=exp_id),
            "traffic_weight": 0.10,
        })
        variants_data[0]["traffic_weight"] = 0.90
    exp = repo.create_experiment(
        exp_id=exp_id,
        name=payload.name,
        description=payload.description,
        base_prompt=payload.base_prompt,
        variants_data=variants_data,
        window_hours=payload.window_hours,
        min_sample_per_variant=payload.min_sample_per_variant,
        confidence_level=payload.confidence_level,
        primary_metric=payload.primary_metric,
        secondary_metric=payload.secondary_metric,
        guardrail_max_delta=payload.guardrail_max_delta,
        early_stop_threshold=payload.early_stop_threshold,
    )
    return exp

@router.get("", response_model=List[ExperimentResponse])
def list_experiments(db: Session = Depends(get_db)):
    repo = ExperimentRepository(db)
    return repo.list_experiments()

@router.get("/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(experiment_id: str, db: Session = Depends(get_db)):
    repo = ExperimentRepository(db)
    exp = repo.get_experiment(experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return exp

@router.patch("/{experiment_id}/status")
def update_experiment_status(
    experiment_id: str, 
    update: ExperimentStatusUpdate, 
    db: Session = Depends(get_db)
):
    repo = ExperimentRepository(db)
    action_map = {
        "START": ExperimentStatus.RUNNING,
        "PAUSE": ExperimentStatus.PAUSED,
        "CONCLUDE": ExperimentStatus.CONCLUDED,
        "STOP_EARLY": ExperimentStatus.STOPPED_EARLY,
        "PROMOTE_B": ExperimentStatus.CONCLUDED
    }

    target_status = action_map.get(update.action.upper())
    if not target_status:
        raise HTTPException(status_code=400, detail=f"Invalid action '{update.action}'.")

    exp = repo.update_status(experiment_id, target_status, reason=update.reason)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return {"message": f"Status updated to {exp.status}", "experiment_id": exp.id, "status": exp.status}

@router.get("/{experiment_id}/metrics")
def get_experiment_metrics(experiment_id: str, db: Session = Depends(get_db)):
    collector = MetricsCollector(db)
    summary = collector.get_experiment_summary(experiment_id)
    if "error" in summary:
        raise HTTPException(status_code=404, detail=summary["error"])
    return summary

@router.post("/{experiment_id}/evaluate")
def evaluate_experiment_decision(experiment_id: str, db: Session = Depends(get_db)):
    engine = DecisionEngine(db)
    evaluation = engine.evaluate_experiment(experiment_id)
    if "error" in evaluation:
        raise HTTPException(status_code=404, detail=evaluation["error"])
    return evaluation
