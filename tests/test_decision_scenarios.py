"""Reproducible PS05 winner, early-stop, and inconclusive decision scenarios."""

import datetime
import asyncio
import unittest
from unittest.mock import AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.decision import DecisionEngine
from core.metrics import MetricsCollector
from core.router import TrafficRouter
from api.main import run_decision_scenarios
from simulator.replayer import CSVReplaySimulator
from db.connection import Base
from db.models import ExperimentStatus
from db.repository import ExperimentRepository


class ProblemStatementScenarioTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def create_running_experiment(self, exp_id, min_sample=20):
        repo = ExperimentRepository(self.session)
        repo.create_experiment(
            exp_id=exp_id,
            name=exp_id,
            base_prompt="control prompt",
            variants_data=[
                {"key": "A", "name": "Control", "content": "control", "traffic_weight": 0.8},
                {"key": "B", "name": "Challenger", "content": "challenger", "traffic_weight": 0.2},
            ],
            min_sample_per_variant=min_sample,
            window_hours=1,
            confidence_level=0.95,
            primary_disposition="BL Enriched",
            early_stop_threshold=0.01,
        )
        repo.update_status(exp_id, ExperimentStatus.RUNNING)
        exp = repo.get_experiment(exp_id)
        exp.started_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
        self.session.commit()
        return repo

    def add_outcomes(self, exp_id, variant, successes, failures, duration_observed=False):
        collector = MetricsCollector(self.session)
        for index in range(successes + failures):
            collector.record_event(
                experiment_id=exp_id,
                variant_key=variant,
                caller_id=f"{variant}-{index}",
                call_id=f"{exp_id}-{variant}-{index}",
                call_duration_sec=70 if variant == "A" else 65,
                duration_observed=duration_observed,
                disposition="BL Enriched" if index < successes else "No Information",
            )

    def test_b_wins_and_is_promoted(self):
        exp_id = "scenario-wins"
        repo = self.create_running_experiment(exp_id)
        self.add_outcomes(exp_id, "A", 10, 40, duration_observed=True)
        self.add_outcomes(exp_id, "B", 40, 10, duration_observed=True)
        result = DecisionEngine(self.session).evaluate_experiment(exp_id)
        self.assertEqual(result["decision"], "PROMOTE_WINNER")
        self.assertEqual(repo.get_experiment(exp_id).deployed_variant_key, "B")

    def test_b_is_clearly_worse_and_stopped(self):
        exp_id = "scenario-harmful"
        repo = self.create_running_experiment(exp_id)
        self.add_outcomes(exp_id, "A", 28, 2)
        self.add_outcomes(exp_id, "B", 0, 10)
        result = DecisionEngine(self.session).evaluate_experiment(exp_id)
        self.assertEqual(result["decision"], "EARLY_STOP")
        self.assertEqual(repo.get_experiment(exp_id).deployed_variant_key, "A")

    def test_expired_weak_evidence_is_inconclusive(self):
        exp_id = "scenario-inconclusive"
        repo = self.create_running_experiment(exp_id)
        self.add_outcomes(exp_id, "A", 2, 3)
        self.add_outcomes(exp_id, "B", 2, 3)
        result = DecisionEngine(self.session).evaluate_experiment(exp_id)
        self.assertEqual(result["decision"], "INCONCLUSIVE")
        self.assertEqual(repo.get_experiment(exp_id).deployed_variant_key, "A")

    def test_router_respects_configured_share_and_is_sticky(self):
        caller = "sticky-test-user"
        bucket = TrafficRouter.get_bucket(caller, "exp-routing")
        variant, _ = TrafficRouter.assign_variant(caller, "exp-routing", min(1.0, bucket + 0.001))
        self.assertEqual(variant, "B")
        self.assertEqual(
            TrafficRouter.assign_variant(caller, "exp-routing", min(1.0, bucket + 0.001))[0],
            variant,
        )

    def test_replay_does_not_count_the_same_call_twice(self):
        exp_id = "scenario-idempotent"
        repo = self.create_running_experiment(exp_id)
        repo.get_experiment(exp_id).started_at = datetime.datetime.utcnow()
        self.session.commit()
        MetricsCollector(self.session).record_event(
            experiment_id=exp_id, variant_key="A", caller_id="caller-1", call_id="same-call",
            call_duration_sec=0, duration_observed=False, disposition="No Information",
        )
        result = asyncio.run(CSVReplaySimulator(self.session).replay_call({
            "caller_id": "caller-1", "call_id": "same-call", "recording_url": "",
            "call_duration_sec": 0, "call_duration_observed": False,
        }, exp_id))
        self.assertEqual(result["status"], "skipped")

    def test_replay_batch_selects_fresh_calls_after_first_sample(self):
        exp_id = "scenario-fresh-sample"
        repo = self.create_running_experiment(exp_id)
        repo.get_experiment(exp_id).started_at = datetime.datetime.utcnow()
        self.session.commit()
        MetricsCollector(self.session).record_event(
            experiment_id=exp_id, variant_key="A", caller_id="caller-old", call_id="old-call",
            call_duration_sec=60, disposition="No Information",
        )
        simulator = CSVReplaySimulator(self.session)
        simulator.load_historical_calls = lambda _: [
            {"call_id": "old-call", "caller_id": "caller-old"},
            {"call_id": "new-call", "caller_id": "caller-new"},
        ]
        simulator.replay_call = AsyncMock(side_effect=lambda call, *_args: {
            "status": "success", "call_id": call["call_id"]
        })

        results = asyncio.run(simulator.replay_batch("unused.csv", exp_id, limit=1))

        self.assertEqual([result["call_id"] for result in results], ["new-call"])

    def test_dashboard_scenario_fixture_returns_all_three_outcomes(self):
        result = run_decision_scenarios(self.session)
        decisions = {item["scenario"]: item["decision"] for item in result["scenarios"]}
        self.assertEqual(decisions, {
            "winner": "PROMOTE_WINNER",
            "harmful": "EARLY_STOP",
            "inconclusive": "INCONCLUSIVE",
        })


if __name__ == "__main__":
    unittest.main()
