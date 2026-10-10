import asyncio
import logging
import os
import datetime
import uuid
from fastapi import FastAPI, Request, Depends, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from db.connection import init_db, get_db, SessionLocal
from db.repository import ExperimentRepository
from api.routes.experiments import router as experiments_router
from api.routes.metrics_ws import ws_router
from simulator.replayer import CSVReplaySimulator
from core.decision import DecisionEngine
from core.metrics import MetricsCollector
from db.models import ExperimentStatus
from api.routes.prompts import router as prompts_router

app = FastAPI(
    title="Voice AI A/B Testing & Auto-Rollout Engine",
    description="Automated experimental platform for AI Voice Bot prompts with Bayesian winner detection and early stop safeguards.",
    version="1.0.0"
)
logger = logging.getLogger(__name__)
_replay_jobs = {}

_decision_monitor_task = None


async def _monitor_running_experiments():
    """Periodically evaluate RUNNING experiments for early stops and window expiry."""
    while True:
        db = SessionLocal()
        try:
            repo = ExperimentRepository(db)
            for experiment in repo.list_experiments():
                if experiment.status == "RUNNING":
                    DecisionEngine(db).evaluate_experiment(experiment.id)
        except Exception:
            # Keep the service alive; a later tick retries transient DB failures.
            logger.exception("Experiment decision monitor failed")
        finally:
            db.close()
        await asyncio.sleep(30)

# Initialize Database tables on startup
@app.on_event("startup")
def startup_event():
    global _decision_monitor_task
    init_db()
    _decision_monitor_task = asyncio.create_task(_monitor_running_experiments())


@app.on_event("shutdown")
async def shutdown_event():
    if _decision_monitor_task:
        _decision_monitor_task.cancel()
        try:
            await _decision_monitor_task
        except asyncio.CancelledError:
            pass

# Routers
app.include_router(experiments_router, prefix="/api")
app.include_router(ws_router)
app.include_router(prompts_router, prefix="/api")

# Template & Static mounting
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "dashboard", "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "dashboard", "templates")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.get("/", response_class=HTMLResponse)
def get_dashboard(request: Request, db: Session = Depends(get_db)):
    repo = ExperimentRepository(db)
    experiments = repo.list_experiments()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"experiments": experiments}
    )

def _replay_job_response(job):
    return {key: value for key, value in job.items() if key != "task"}


async def _run_full_replay(job_id: str, experiment_id: str, csv_path: str):
    job = _replay_jobs[job_id]
    db = SessionLocal()
    try:
        job["status"] = "running"
        replayer = CSVReplaySimulator(db)

        def on_progress(completed, total, result):
            job["completed"] = completed
            job["total"] = total
            job["counts"][result.get("evaluation_mode") or result.get("status", "unknown")] += 1
            summary = {key: result.get(key) for key in (
                "call_id", "status", "assigned_variant", "disposition", "evaluation_mode", "error_message", "fallback_reason", "message"
            ) if result.get(key) is not None}
            job["recent_results"].append(summary)
            job["recent_results"] = job["recent_results"][-10:]

        await replayer.replay_batch(csv_path, experiment_id=experiment_id, progress_callback=on_progress)
        job["decision"] = DecisionEngine(db).evaluate_experiment(experiment_id)
        job["status"] = "completed"
    except Exception as exc:
        logger.exception("Full CSV replay job %s failed", job_id)
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        db.close()


@app.post("/api/simulator/replay-demo", status_code=202)
async def trigger_demo_replay(experiment_id: str, db: Session = Depends(get_db)):
    exp = ExperimentRepository(db).get_experiment(experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    if exp.status != "RUNNING":
        raise HTTPException(status_code=409, detail=f"Experiment is {exp.status}; start it before replaying calls.")
    existing = next((job for job in _replay_jobs.values()
                     if job["experiment_id"] == experiment_id and job["status"] in {"queued", "running"}), None)
    if existing:
        return _replay_job_response(existing)

    csv_path = os.path.join(BASE_DIR, "data", "sample_calls.csv")
    replayer = CSVReplaySimulator(db)
    csv_calls = replayer.load_historical_calls(csv_path)
    pending_count = sum(1 for row in csv_calls if not (
        row.get("call_id") and replayer.repo.get_event_by_call_id(experiment_id, str(row["call_id"]))
    ))
    job_id = f"replay_{uuid.uuid4().hex[:10]}"
    job = {"job_id": job_id, "experiment_id": experiment_id, "status": "queued",
           "completed": 0, "total": pending_count,
           "counts": {"simulated_counterfactual": 0, "historical_csv_fallback": 0, "skipped": 0, "routed": 0, "error": 0},
           "recent_results": [], "note": "Sarvam results are model-generated estimates; CSV fallback results are historical labels, not prompt impact."}
    _replay_jobs[job_id] = job
    job["task"] = asyncio.create_task(_run_full_replay(job_id, experiment_id, csv_path))
    return _replay_job_response(job)


@app.get("/api/simulator/replay-demo/{job_id}")
def get_replay_status(job_id: str):
    job = _replay_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Replay job not found; it may have expired after a server restart.")
    return _replay_job_response(job)


@app.post("/api/simulator/demo-scenarios")
def run_decision_scenarios(db: Session = Depends(get_db)):
    """Create isolated, clearly synthetic PS05 scenarios for a judge-facing demo."""
    repo = ExperimentRepository(db)
    fixtures = {
        "winner": {"a": (10, 40), "b": (40, 10)},
        "harmful": {"a": (28, 2), "b": (0, 10)},
        "inconclusive": {"a": (2, 3), "b": (2, 3)},
    }
    outputs = []
    for name, outcomes in fixtures.items():
        exp_id = f"demo_ps05_{name}"
        if repo.get_experiment(exp_id):
            outputs.append({"scenario": name, "experiment_id": exp_id,
                            "status": "already_exists", "message": "Existing fixture preserved; delete it manually to regenerate."})
            continue
        repo.create_experiment(
            exp_id=exp_id,
            name=f"PS05 Synthetic Demo: {name.title()}",
            description="Deterministic synthetic fixture; not Sarvam or customer outcome data.",
            base_prompt="Synthetic demo control prompt",
            variants_data=[
                {"key": "A", "name": "Control", "content": "Control fixture", "traffic_weight": 0.5},
                {"key": "B", "name": "Challenger", "content": "Challenger fixture", "traffic_weight": 0.5},
            ],
            window_hours=1,
            min_sample_per_variant=20,
            confidence_level=0.95,
            primary_disposition="BL Enriched",
            guardrail_max_delta=30,
            early_stop_threshold=0.01,
        )
        repo.update_status(exp_id, ExperimentStatus.RUNNING)
        experiment = repo.get_experiment(exp_id)
        experiment.started_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
        db.commit()

        collector = MetricsCollector(db)
        for variant in ("A", "B"):
            successes, failures = outcomes[variant.lower()]
            duration = 70 if variant == "A" else 65
            for index in range(successes + failures):
                collector.record_event(
                    experiment_id=exp_id,
                    variant_key=variant,
                    caller_id=f"{exp_id}-{variant}-{index}",
                    call_id=f"{exp_id}-{variant}-{index}",
                    call_duration_sec=duration,
                    duration_observed=True,
                    disposition="BL Enriched" if index < successes else "No Information",
                )
        decision = DecisionEngine(db).evaluate_experiment(exp_id)
        outputs.append({"scenario": name, "experiment_id": exp_id,
                        "decision": decision.get("decision"), "reason": decision.get("reason"),
                        "samples": decision.get("samples"), "status": decision.get("status")})
    return {"message": "Synthetic PS05 fixtures only; these are not real customer or Sarvam results.",
            "scenarios": outputs}
