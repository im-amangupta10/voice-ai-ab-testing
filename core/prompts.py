"""Prompt helpers used when creating experiments."""

import random
from typing import Optional


CHALLENGER_MUTATIONS = (
    "Keep the conversation concise and prioritize resolving the buyer's main requirement before collecting optional details.",
    "Use a warmer, more consultative tone while preserving every safety, language, and transfer restriction in the base prompt.",
    "When the buyer shows clear intent, move efficiently toward the next permitted action and avoid unnecessary repetition.",
    "Prefer short, natural responses and ask only the next eligible question required by the collection rules.",
    "Acknowledge the buyer's concern briefly, then guide the conversation toward a concrete resolution or valid closing.",
)


def generate_challenger_prompt(base_prompt: str, seed: Optional[str] = None) -> str:
    """Create a reproducible challenger prompt derived from A."""
    rng = random.Random(seed)
    mutations = rng.sample(CHALLENGER_MUTATIONS, 2)
    return (
        f"{base_prompt.rstrip()}\n\n"
        "--- EXPERIMENTAL CHALLENGER INSTRUCTIONS ---\n"
        "Apply these instructions only when they do not conflict with the base prompt:\n"
        f"- {mutations[0]}\n"
        f"- {mutations[1]}\n"
    )
