import os
import httpx
from typing import Dict, Any, Optional

class SarvamVoiceAgentClient:
    """
    Client interface for integrating Sarvam AI Platform voice models and agents.
    Provides methods for testing prompt variations, text-to-speech, and simulated conversational turns.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.sarvam.ai"
    ):
        self.api_key = api_key or os.environ.get("SARVAM_API_KEY", "MOCK_SARVAM_KEY")
        self.base_url = base_url
        self.is_mock = self.api_key.startswith("MOCK_") or not api_key

    async def generate_agent_response(
        self,
        prompt: str,
        user_utterance: str,
        conversation_history: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Sends conversation prompt and caller utterance to Sarvam conversational endpoint.
        Falls back to mock simulation if running offline/without API credentials.
        """
        if self.is_mock:
            # Deterministic mock response for offline replay testing
            is_positive = any(word in user_utterance.lower() for word in ["yes", "interested", "available", "sure", "book"])
            return {
                "status": "success",
                "mock": True,
                "agent_reply": "Certainly! I have scheduled our follow-up meeting as requested." if is_positive else "I understand, thank you for your time.",
                "inferred_disposition": "MEETING_FIXED" if is_positive else "DECLINED",
                "prompt_tokens": len(prompt.split()),
            }

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "system_prompt": prompt,
            "user_message": user_utterance,
            "history": conversation_history or []
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "status": "success",
                    "mock": False,
                    "raw_response": data,
                    "inferred_disposition": "MEETING_FIXED" # Evaluated by downstream parser
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error_message": str(e),
                    "mock": False,
                }
