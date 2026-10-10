import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session
from db.models import ExperimentModel, ExperimentStatus
from db.repository import ExperimentRepository
from core.metrics import MetricsCollector
from core.stats import StatisticalEngine

class DecisionEngine:
    """
    Automated Rollout and Early-Stop Decision Engine.
    Evaluates current evidence and takes action:
      - Auto-promote B to 100% traffic if P(B > A) >= 0.95 & min_sample reached & guardrails safe.
      - Auto-stop B immediately if P(B > A) <= early_stop_threshold (0.01) after minimum look sample.
      - Inconclusive if window expires without clear winner.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = ExperimentRepository(db)
        self.metrics_collector = MetricsCollector(db)

    def evaluate_experiment(self, experiment_id: str) -> Dict[str, Any]:
        exp = self.repo.get_experiment(experiment_id)
        if not exp:
            return {"error": "Experiment not found"}

        if exp.status != ExperimentStatus.RUNNING.value:
            return {
                "experiment_id": experiment_id,
                "status": exp.status,
                "decision": "NO_EVALUATION",
                "message": f"Experiment is in {exp.status} status (not RUNNING)."
            }

        summary = self.metrics_collector.get_experiment_summary(experiment_id)
        metrics = summary["metrics"]
        var_a = metrics["variant_A"]
        var_b = metrics["variant_B"]

        # 1. Compute Bayesian Probability P(B > A)
        p_b_wins = StatisticalEngine.compute_bayesian_win_probability(
            success_a=var_a["goal_successes"],
            total_a=var_a["total_calls"],
            success_b=var_b["goal_successes"],
            total_b=var_b["total_calls"],
        )

        # 2. Check Secondary Guardrail (Call Duration)
        guardrail = metrics["guardrail"]
        if guardrail["available"]:
            is_guardrail_safe, guardrail_msg = StatisticalEngine.check_duration_guardrail(
                duration_a=var_a["avg_duration_sec"],
                duration_b=var_b["avg_duration_sec"],
                max_allowed_delta=exp.guardrail_max_delta,
            )
        else:
            is_guardrail_safe = False
            guardrail_msg = "Duration guardrail not evaluated: reliable call-duration data is unavailable."

        decision = "CONTINUE_TESTING"
        reason = "Evidence still accumulating."
        action_taken = None

        min_sample = exp.min_sample_per_variant
        has_min_sample = (var_a["total_calls"] >= min_sample and var_b["total_calls"] >= min_sample)
        # Early stop check requires at least 25% of min sample to avoid spurious initial rolls
        early_stop_min = max(5, int(min_sample * 0.25))
        # Require enough evidence in both arms before making a harmful-variant call.
        has_early_stop_sample = (
            var_a["total_calls"] >= early_stop_min and var_b["total_calls"] >= early_stop_min
        )

        # Rule A: Clearly Harmful -> EARLY STOP
        started_at = exp.started_at or exp.created_at
        window_ended = (datetime.datetime.utcnow() - started_at).total_seconds() >= exp.window_hours * 3600

        if has_early_stop_sample and p_b_wins <= exp.early_stop_threshold:
            decision = "EARLY_STOP"
            reason = f"Variant B is harmful: P(B>A) = {p_b_wins:.4f} <= threshold {exp.early_stop_threshold}."
            self.repo.update_status(experiment_id, ExperimentStatus.STOPPED_EARLY, reason=reason,
                                    promoted_variant_key="A", decision_evidence={
                                        "decision": decision, "p_b_wins": p_b_wins,
                                        "early_stop_threshold": exp.early_stop_threshold,
                                        "samples_a": var_a["total_calls"], "samples_b": var_b["total_calls"],
                                        "goal": exp.primary_disposition,
                                    })
            action_taken = "Traffic reverted 100% to Control Variant A."

        # Rule B: Guardrail severely breached -> EARLY STOP / PAUSE
        elif guardrail["available"] and not is_guardrail_safe and has_early_stop_sample:
            decision = "EARLY_STOP_GUARDRAIL"
            reason = guardrail_msg
            self.repo.update_status(experiment_id, ExperimentStatus.STOPPED_EARLY, reason=reason,
                                    promoted_variant_key="A", decision_evidence={
                                        "decision": decision, "samples_a": var_a["total_calls"],
                                        "samples_b": var_b["total_calls"], "guardrail": guardrail,
                                    })
            action_taken = "Variant B halted due to guardrail breach."

        # Rule C: Winner declared -> PROMOTE B
        elif window_ended and has_min_sample and p_b_wins >= exp.confidence_level and guardrail["available"] and is_guardrail_safe:
            decision = "PROMOTE_WINNER"
            reason = f"Variant B statistically validated: P(B>A) = {p_b_wins:.4f} >= {exp.confidence_level}."
            self.repo.update_status(experiment_id, ExperimentStatus.CONCLUDED, reason=reason,
                                    promoted_variant_key="B", decision_evidence={
                                        "decision": decision, "p_b_wins": p_b_wins,
                                        "confidence_threshold": exp.confidence_level,
                                        "samples_a": var_a["total_calls"], "samples_b": var_b["total_calls"],
                                        "goal": exp.primary_disposition, "guardrail": guardrail,
                                    })
            action_taken = "Variant B promoted to 100% of traffic. Set as new baseline."
        elif window_ended:
            decision = "INCONCLUSIVE"
            reason = (guardrail_msg if has_min_sample and p_b_wins >= exp.confidence_level and not guardrail["available"]
                      else f"Experiment window expired after {exp.window_hours} hours without meeting the decision rule. "
                           f"A={var_a['total_calls']}, B={var_b['total_calls']}; minimum per variant={min_sample}.")
            self.repo.update_status(experiment_id, ExperimentStatus.CONCLUDED, reason=reason,
                                    promoted_variant_key="A", decision_evidence={
                                        "decision": decision, "p_b_wins": p_b_wins,
                                        "samples_a": var_a["total_calls"], "samples_b": var_b["total_calls"],
                                        "goal": exp.primary_disposition,
                                    })
            action_taken = "No winner; control A remains deployed."

        return {
            "experiment_id": experiment_id,
            "status": self.repo.get_experiment(experiment_id).status,
            "primary_goal": exp.primary_disposition,
            "window_ended": window_ended,
            "p_b_wins": p_b_wins,
            "decision": decision,
            "reason": reason,
            "action_taken": action_taken,
            "samples": {
                "calls_A": var_a["total_calls"],
                "calls_B": var_b["total_calls"],
                "min_sample_required": min_sample,
                "has_min_sample": has_min_sample
            },
            "guardrail_status": {
                "is_safe": guardrail["is_safe"],
                "message": guardrail_msg
            }
        }
