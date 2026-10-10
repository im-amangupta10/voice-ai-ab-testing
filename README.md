# Voice AI A/B Testing & Auto-Rollout Engine
> **Hackathon Problem Statement 05** | Safe, Statistical AI Voice Bot Experimentation

This repository provides a simulator-backed A/B workflow for AI Voice Bot prompts. It routes caller IDs stickily, evaluates a configurable disposition goal, uses a Bayesian posterior decision rule, and applies the winner/control route after a decision. Sarvam replay outcomes are simulated counterfactuals, not live customer outcomes.

---

## 🏗️ Architecture & Completed Foundations

### 1. Implemented foundations:
- **Experiment Manager (`core/experiment.py`, `db/models.py`)**: Pydantic schemas and SQLAlchemy models for immutable experiments, variant pairs (A vs B), and lifecycle states (`DRAFT`, `RUNNING`, `PAUSED`, `CONCLUDED`, `STOPPED_EARLY`).
- **Deterministic Traffic Router (`core/router.py`)**: SHA-256 hash-based sticky bucketing (`O(1)` complexity) ensuring the same caller always receives the same prompt variant across the test window.
- **Event Store & Database (`db/`)**: SQLite database with indexed tables: `experiments`, `variants`, `call_events`, and `audit_logs`.
- **Metrics Collector (`core/metrics.py`)**: Goal conversion, split accuracy, and 95% Beta posterior credible intervals. Duration values are included only when sourced from an explicit call-duration field.
- **Presentation Layer & Live Dashboard (`api/`, `dashboard/`)**:
  - FastAPI backend serving REST API endpoints (`/api/experiments`, `/api/experiments/{id}/metrics`).
  - Interactive dark-themed web dashboard with real-time WebSocket metrics streaming (`/ws/metrics/{id}`).
  - Controls to replay calls, evaluate automated decisions, manually promote, or early stop.

### 2. Experiment decisions and simulator limitations:
- **Statistical Engine (`core/stats.py`)**: Beta-Binomial posterior probability `P(B > A)` with a Beta(1,1) prior. This is a Bayesian decision threshold, not a frequentist p-value; the configured posterior threshold remains interpretable under repeated looks.
- **Decision Engine (`core/decision.py`)**: Checks early-stop safety, waits for the configured window before promotion, returns an inconclusive outcome at expiry, and records decision evidence. A periodic service monitor evaluates running experiments.
- **Sarvam replay (`simulator/`)**: Saaras transcription plus Sarvam Chat prompt simulation. Outputs are generated counterfactual estimates; they must not be presented as observed causal lift. Longer-than-30-second recordings require Batch STT, which is not wired up yet.

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
2. Click **"▶ Replay Sample Calls"** to replay a bounded, deterministic sample through Sarvam and the sticky router.
3. Observe conversion estimates, credible intervals, split audit, and the Bayesian posterior meter.
4. Decisions are checked periodically and after each replay batch; **"🤖 Evaluate Decision"** requests an immediate check.
5. Use **"🧪 Run PS05 Scenarios"** to create isolated synthetic winner, harmful, and inconclusive experiments for the required decision-path demo.

### 4. Replay the IndiaMART export

Convert the attached IndiaMART call log into the simulator schema:

```bash
python3 data/process_indiamart_csv.py \
  /path/to/Call_Logs_Hackathon.csv data/sample_calls.csv
```

The converter normalizes spreadsheet-style IDs (for example, `275890790.0`
becomes `275890790`), preserves the original disposition, marks `BL Enriched`,
`BL Approved`, and `BL Generated` as successful outcomes, and uses duration
only when the export contains an explicit duration column. Record timestamps
are not treated as call duration.
The generated `data/sample_calls.csv` is then replayed by the dashboard endpoint.
The supplied IndiaMART export has no explicit duration column; consequently,
the duration guardrail displays **unavailable** and the decision engine will
not auto-promote B on that data alone. The reproducible win scenario uses
explicit synthetic duration observations to exercise the promotion path.

### 7. Sarvam recording evaluation

Replay downloads each HTTPS `recording_url`, transcribes it with Sarvam Saaras
(`saaras:v4`), then sends the transcript plus the routed A/B prompt to Sarvam
Chat Completions (`sarvam-105b`). Chat simulates the selected agent prompt on
the historical buyer scenario and returns a JSON disposition, confidence,
evidence, and short simulated exchange. Only completed simulations are written
to the event store. Configure:

The dashboard button replays up to 10 rows with available recordings to keep the demo bounded. The
API accepts `limit=1..100` for a curated run; it does not launch the full CSV.

```bash
export SARVAM_API_KEY="..."
```

Optional `SARVAM_CHAT_MODEL` selects another supported chat model. The current
synchronous transcription endpoint accepts recordings up to 30 seconds; longer
recordings are returned as failures and are not counted (use Sarvam Batch STT
for those). Missing or inaccessible recording URLs are likewise skipped.

Important evaluation limitation: this is a model-generated counterfactual
replay, not a real randomized customer test. It is useful for a hackathon demo
of deterministic routing, prompt application, and disposition scoring, but
Bayesian probabilities and conversion differences must be presented as
simulated estimates—not causal or production lift. Validate with live traffic
before rollout. When the source export has no explicit call-duration column,
the dashboard marks the duration guardrail unavailable rather than inventing
audio duration from record update timestamps.

### 5. PS05 decision scenario tests

Run the reproducible winner (including guardrail), harmful-variant early stop,
inconclusive-window, sticky-routing, and duplicate-replay checks with:

```bash
venv/bin/python -m unittest discover -s tests -v
```

### 6. Add prompts from the dashboard

When creating an experiment, choose **Upload** and select the original `.docx`
prompt (or upload a `.txt`/`.md` file). The server extracts the prompt as
Variant A and automatically creates a reproducible Variant B by adding two
controlled challenger instructions. Both complete prompt versions are stored
with the experiment and are available for a future Sarvam agent replay.
