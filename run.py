import uvicorn
import os
import sys

# Ensure current repository is on python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

if __name__ == "__main__":
    print("🚀 Starting Voice AI A/B Testing & Auto-Rollout Engine...")
    print("📊 Dashboard available at: http://localhost:8000")
    print("📖 API Documentation at:   http://localhost:8000/docs")
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
