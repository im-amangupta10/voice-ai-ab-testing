import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from db.connection import get_db
from core.metrics import MetricsCollector

ws_router = APIRouter(tags=["WebSocket"])

@ws_router.websocket("/ws/metrics/{experiment_id}")
async def websocket_metrics_stream(websocket: WebSocket, experiment_id: str, db: Session = Depends(get_db)):
    await websocket.accept()
    collector = MetricsCollector(db)
    try:
        while True:
            summary = collector.get_experiment_summary(experiment_id)
            if "error" not in summary:
                p_win = summary["posterior_probability_b_wins"]
                summary["bayesian_p_b_wins"] = p_win

            await websocket.send_json(summary)
            await asyncio.sleep(2.0) # push updates every 2s
    except WebSocketDisconnect:
        pass
    except Exception:
        await websocket.close()
