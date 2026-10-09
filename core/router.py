import hashlib
from typing import Dict, Any, Tuple

class TrafficRouter:
    """
    Deterministic O(1) Traffic Router.
    Uses SHA-256 hash bucketing to assign incoming caller IDs sticky to variants.
    """

    @staticmethod
    def get_bucket(caller_id: str, experiment_id: str) -> float:
        """
        Computes a deterministic bucket float between 0.0000 and 0.9999 for the caller.
        """
        hash_input = f"{caller_id}:{experiment_id}"
        hash_hex = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        # Convert first 8 hex characters to int and mod by 10000
        bucket_int = int(hash_hex[:8], 16) % 10000
        return bucket_int / 10000.0

    @classmethod
    def assign_variant(
        cls, 
        caller_id: str, 
        experiment_id: str, 
        b_traffic_weight: float = 0.10
    ) -> Tuple[str, float]:
        """
        Assigns caller to variant 'A' or 'B'.
        If bucket < b_traffic_weight -> 'B', else 'A'.
        Returns: (variant_key, bucket_score)
        """
        bucket = cls.get_bucket(caller_id, experiment_id)
        variant = "B" if bucket < b_traffic_weight else "A"
        return variant, bucket

    @staticmethod
    def audit_split_accuracy(
        total_calls_a: int, 
        total_calls_b: int, 
        configured_b_weight: float
    ) -> Dict[str, Any]:
        """
        Computes achieved traffic share vs configured traffic share and evaluates split drift.
        """
        total = total_calls_a + total_calls_b
        if total == 0:
            return {
                "total_calls": 0,
                "achieved_b_share": 0.0,
                "configured_b_share": configured_b_weight,
                "drift": 0.0,
                "is_aligned": True,
            }

        achieved_b_share = round(total_calls_b / total, 4)
        drift = round(abs(achieved_b_share - configured_b_weight), 4)
        
        # In small sample sizes (N < 100), variance is expected. For large N, flag if drift > 0.05
        max_allowed_drift = 0.10 if total < 100 else 0.03
        is_aligned = drift <= max_allowed_drift

        return {
            "total_calls": total,
            "calls_a": total_calls_a,
            "calls_b": total_calls_b,
            "achieved_b_share": achieved_b_share,
            "configured_b_share": configured_b_weight,
            "drift": drift,
            "is_aligned": is_aligned,
        }
