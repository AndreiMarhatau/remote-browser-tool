"""Tests for the local/manual LLM provider."""

from remote_browser_tool.config import LLMConfig
from remote_browser_tool.factory import build_llm
from remote_browser_tool.llm.base import LLMContext
from remote_browser_tool.models import DirectiveStatus


def _context() -> LLMContext:
    return LLMContext(task_description="Example", memory=[], history=[])


def test_local_llm_requests_manual_intervention() -> None:
    config = LLMConfig(provider="local")

    llm = build_llm(config)
    directive = llm.complete("ignored", _context())

    assert directive.status is DirectiveStatus.WAIT_FOR_USER
    assert directive.user_request is not None
    assert "Connect to the VNC session" in directive.user_request.instructions
    assert "Manual control required" in (directive.message or "")

    conversation = llm.start_conversation()
    assert conversation
    assert conversation[0].role == "system"
    assert "Local mode" in conversation[0].content


def test_local_llm_uses_custom_parameters() -> None:
    config = LLMConfig(
        provider="local",
        parameters={
            "message": "Please take over",
            "reason": "Need manual assistance",
            "instructions": "Handle the step manually",
            "allow_finish_without_return": True,
            "system_prompt": "",
        },
    )

    llm = build_llm(config)
    directive = llm.complete("ignored", _context())

    assert directive.message == "Please take over"
    assert directive.user_request is not None
    assert directive.user_request.reason == "Need manual assistance"
    assert directive.user_request.instructions == "Handle the step manually"
    assert directive.user_request.allow_finish_without_return is True

    assert llm.start_conversation() == []

