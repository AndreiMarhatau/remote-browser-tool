"""LLM client that hands control over to a human operator."""

from __future__ import annotations

from typing import List

from ..config import LLMConfig
from ..models import DirectiveStatus, LLMDirective, UserInterventionRequest
from .base import ConversationTurn, LLMClient, LLMContext


class LocalLLM(LLMClient):
    """An LLM implementation that always requests manual intervention."""

    def __init__(self, config: LLMConfig) -> None:
        params = config.parameters or {}
        self._message = params.get(
            "message",
            (
                "Manual control required. Complete the next step in the browser and "
                "confirm completion in the portal."
            ),
        )
        self._request = UserInterventionRequest(
            reason=params.get(
                "reason",
                "Local provider active – awaiting human control.",
            ),
            instructions=params.get(
                "instructions",
                (
                    "Connect to the VNC session, perform the necessary actions, "
                    "then click 'Finished' in the portal."
                ),
            ),
            allow_finish_without_return=params.get(
                "allow_finish_without_return",
                False,
            ),
        )
        self._system_prompt = params.get(
            "system_prompt",
            "Local mode active. No automated planning will be performed.",
        )

    def complete(self, prompt: str, context: LLMContext) -> LLMDirective:
        return LLMDirective(
            status=DirectiveStatus.WAIT_FOR_USER,
            message=self._message,
            user_request=self._request,
        )

    def start_conversation(self) -> List[ConversationTurn]:
        if not self._system_prompt:
            return []
        return [ConversationTurn(role="system", content=self._system_prompt)]

