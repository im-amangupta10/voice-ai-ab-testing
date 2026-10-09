# Voice AI A/B Testing & Auto-Rollout Engine
> **Hackathon Problem Statement 05** | Safe, Statistical AI Voice Bot Experimentation

This repository provides an automated A/B testing workflow for AI Voice Bot prompts. It allows testing a challenger prompt on a configurable slice of traffic (e.g. 10%), measuring performance against primary (Meeting Fixed Rate) and secondary guardrail metrics (Call Duration), declaring statistically valid winners, and automatically stopping harmful variants.

---

## 🏗️ Architecture & Completed Foundations

### 1. Fully Implemented Layers:
- **Experiment Manager (`core/experiment.py`, `db/models.py`)**: Pydantic schemas and SQLAlchemy models for immutable experiments, variant pairs (A vs B), and lifecycle states (`DRAFT`, `RUNNING`, `PAUSED`, `CONCLUDED`, `STOPPED_EARLY`).
- **Deterministic Traffic Router (`core/router.py`)**: SHA-256 hash-based sticky bucketing (`O(1)` complexity) ensuring the same caller always receives the same prompt variant across the test window.
- **Event Store & Database (`db/`)**: SQLite database with indexed tables: `experiments`, `variants`, `call_events`, and `audit_logs`.
- **Metrics Collector (`core/metrics.py`)**: Real-time aggregate queries calculating total calls, meeting conversion rates, average durations, and split accuracy audits.
- **Presentation Layer & Live Dashboard (`api/`, `dashboard/`)**:
  - FastAPI backend serving REST API endpoints (`/api/experiments`, `/api/experiments/{id}/metrics`).
  - Interactive dark-themed web dashboard with real-time WebSocket metrics streaming (`/ws/metrics/{id}`).
  - Controls to replay calls, evaluate automated decisions, manually promote, or early stop.

### 2. Modular Skeletons & Stubs:
- **Sarvam AI Platform Simulator (`simulator/sarvam_client.py`, `simulator/replayer.py`)**: Client wrapper for Sarvam AI voice models and prompt endpoints with an offline mock fallback and a CSV replay harness.
- **Statistical Engine (`core/stats.py`)**: Beta-Binomial Bayesian Monte Carlo simulation (`P(B > A)`), SPRT guardrail boundary checks, and sample size calculator.
- **Decision Engine (`core/decision.py`)**: Automated promotion rule (`P >= 0.95` with guardrail check) and early stop rule (`P <= 0.01`).

---

## 🚀 Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch the Application
```bash
python run.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.
API documentation is available at **[http://localhost:8000/docs](http://localhost:8000/docs)**.

### 3. Quick Demo Walkthrough:
1. Click **"+ New Experiment"** on the dashboard.
2. Click **"▶ Replay Sample Calls"** to simulate incoming calls through the deterministic router.
3. Observe live metric updates for Variant A vs Variant B and the confidence meter.
4. Click **"🤖 Evaluate Decision"** to run the automated statistical rule engine.

### 4. Replay the IndiaMART export

Convert the attached IndiaMART call log into the simulator schema:

```bash
python3 data/process_indiamart_csv.py \
  /path/to/Call_Logs_Hackathon.csv data/sample_calls.csv
```

The converter normalizes spreadsheet-style IDs (for example, `275890790.0`
becomes `275890790`), preserves the original disposition, marks `BL Enriched`,
`BL Approved`, and `BL Generated` as successful outcomes, and derives a
minute-resolution duration from `entered_on` and `last_modified_date`.
The generated `data/sample_calls.csv` is then replayed by the dashboard endpoint.
