import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from db.connection import get_db
from core.metrics import MetricsCollector
from core.stats import StatisticalEngine

ws_router = APIRouter(tags=["WebSocket"])

@ws_router.websocket("/ws/metrics/{experiment_id}")
async def websocket_metrics_stream(websocket: WebSocket, experiment_id: str, db: Session = Depends(get_db)):
    await websocket.accept()
    collector = MetricsCollector(db)
    try:
        while True:
            summary = collector.get_experiment_summary(experiment_id)
            if "error" not in summary:
                metrics = summary["metrics"]
                var_a = metrics["variant_A"]
                var_b = metrics["variant_B"]
                p_win = StatisticalEngine.compute_bayesian_win_probability(
                    var_a["meetings_fixed"], var_a["total_calls"],
                    var_b["meetings_fixed"], var_b["total_calls"]
                )
                summary["bayesian_p_b_wins"] = p_win

            await websocket.send_json(summary)
            await asyncio.sleep(2.0) # push updates every 2s
    except WebSocketDisconnect:
        pass
    except Exception:
        await websocket.close()
