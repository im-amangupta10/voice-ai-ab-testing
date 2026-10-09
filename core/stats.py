from typing import Tuple, Dict, Any
import numpy as np

class StatisticalEngine:
    """
    Statistical engine for evaluating Voice AI A/B testing winners and guardrails.
    [STUB / FOUNDATION LAYER]: Implements standard Bayesian Monte Carlo sampling
    with uniform Beta prior, sample sizing, and SPRT guardrail skeleton.
    """

    @staticmethod
    def compute_bayesian_win_probability(
        success_a: int,
        total_a: int,
        success_b: int,
        total_b: int,
        n_samples: int = 10000
    ) -> float:
        """
        Calculates P(Conversion_B > Conversion_A) using Beta-Binomial conjugate update
        with a non-informative flat prior Beta(1, 1).
        """
        if total_a == 0 or total_b == 0:
            return 0.50 # No evidence yet

        # Posterior parameters
        alpha_a = 1 + success_a
        beta_a = 1 + (total_a - success_a)

        alpha_b = 1 + success_b
        beta_b = 1 + (total_b - success_b)

        # Draw Monte Carlo samples
        samples_a = np.random.beta(alpha_a, beta_a, size=n_samples)
        samples_b = np.random.beta(alpha_b, beta_b, size=n_samples)

        # Fraction of times B's conversion probability was strictly greater than A's
        p_b_wins = float(np.mean(samples_b > samples_a))
        return round(p_b_wins, 4)

    @staticmethod
    def check_guardrail_sprt(
        duration_a: float,
        duration_b: float,
        max_allowed_delta: float = 30.0
    ) -> Tuple[bool, str]:
        """
        [STUB]: Checks whether the secondary guardrail (Call Duration) has breached
        acceptable boundaries.
        Returns: (is_safe: bool, reason: str)
        """
        delta = duration_b - duration_a
        if delta > max_allowed_delta:
            return False, f"Guardrail breached: Variant B duration exceeds A by {delta:.1f}s (limit: {max_allowed_delta}s)"
        return True, "Guardrail safe: Call duration within acceptable boundary."

    @staticmethod
    def calculate_sample_size(
        baseline_rate: float = 0.15,
        mde: float = 0.03,
        alpha: float = 0.05,
        beta: float = 0.20
    ) -> int:
        """
        [STUB]: Standard two-proportion minimum sample size formula per variant.
        Default parameters reflect 15% baseline conversion with 3% minimum detectable effect.
        """
        # Approximated sample size (roughly 1,100 - 1,500 calls per variant)
        p1 = baseline_rate
        p2 = baseline_rate + mde
        p_bar = (p1 + p2) / 2.0
        
        # Z-scores for alpha=0.05 (1.96) and power=0.80 (0.84)
        z_alpha = 1.96
        z_beta = 0.84
        
        numerator = (z_alpha * np.sqrt(2 * p_bar * (1 - p_bar)) + z_beta * np.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
        denominator = (p2 - p1) ** 2
        
        if denominator == 0:
            return 1000
        n_per_variant = int(np.ceil(numerator / denominator))
        return max(n_per_variant, 50)
