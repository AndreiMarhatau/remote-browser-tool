"""Prompt construction utilities."""

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

from ..browser.base import BrowserState
from ..config import TaskConfig
from ..llm.base import ConversationTurn
from ..models import BrowserAction, BrowserActionType, MemoryEntry


class PromptBuilder:
    """Build prompts for the LLM based on the current state."""

    def build(
        self,
        task: TaskConfig,
        state: BrowserState,
        memory: Iterable[MemoryEntry],
        history: Iterable[ConversationTurn],
    ) -> str:
        memory_section = "\n".join(f"- {entry.content}" for entry in memory)
        if not memory_section:
            memory_section = "(empty)"
        history_section = "\n".join(f"{turn.role}: {turn.content}" for turn in history)
        if not history_section:
            history_section = "(no prior conversation)"
        state_lines = [
            f"Current URL: {state.url or 'unknown'}",
            f"Page title: {state.title or 'unknown'}",
            f"Focused element: {state.last_action or 'unknown'}",
        ]
        state_section = "\n".join(state_lines)
        prompt = dedent(
            f"""
            You are an automation agent operating a web browser to complete the following task:
            "{task.description}"

            Additional context or success criteria: "{task.goal or 'None provided'}"

            Existing memory entries:
            {memory_section}

            Conversation so far:
            {history_section}

            Browser state:
            {state_section}

            Respond with a JSON object containing the keys:
            status, message, actions, wait_seconds, user_request, memory_to_write, failure_reason.
            The actions field must be a list where each item has keys matching this schema:
            {self._actions_schema()}

            Allowed status values: continue, wait_for_user, wait, finished, failed.
            If you request user help, populate user_request with an object containing
            "reason" and "instructions". Provide only valid JSON with double quotes.
            """
        ).strip()
        return prompt

    @staticmethod
    def _actions_schema() -> str:
        examples = [
            BrowserAction(type=BrowserActionType.NAVIGATE, url="https://example.com"),
            BrowserAction(type=BrowserActionType.CLICK, selector="#submit"),
            BrowserAction(
                type=BrowserActionType.TYPE,
                selector="input[name=email]",
                text="user@example.com",
            ),
            BrowserAction(type=BrowserActionType.WAIT_FOR_SELECTOR, selector="#result", timeout=10),
            BrowserAction(type=BrowserActionType.WAIT, seconds=5),
        ]
        return "\n".join(action.model_dump_json() for action in examples)


