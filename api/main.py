import os
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from db.connection import init_db, get_db
from db.repository import ExperimentRepository
from api.routes.experiments import router as experiments_router
from api.routes.metrics_ws import ws_router
from simulator.replayer import CSVReplaySimulator

app = FastAPI(
    title="Voice AI A/B Testing & Auto-Rollout Engine",
    description="Automated experimental platform for AI Voice Bot prompts with Bayesian winner detection and early stop safeguards.",
    version="1.0.0"
)

# Initialize Database tables on startup
@app.on_event("startup")
def startup_event():
    init_db()

# Routers
app.include_router(experiments_router, prefix="/api")
app.include_router(ws_router)

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

@app.post("/api/simulator/replay-demo")
async def trigger_demo_replay(experiment_id: str, db: Session = Depends(get_db)):
    csv_path = os.path.join(BASE_DIR, "data", "sample_calls.csv")
    replayer = CSVReplaySimulator(db)
    results = await replayer.replay_batch(csv_path, experiment_id=experiment_id)
    return {"message": f"Successfully replayed {len(results)} sample calls.", "replayed_count": len(results)}
