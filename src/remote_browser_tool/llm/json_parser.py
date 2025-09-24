"""Utilities for parsing LLM responses into directives."""

from __future__ import annotations

import json
from typing import Any

from ..models import LLMDirective


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object found in *text* and return it as a dict."""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = _strip_code_fence(cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response")
    snippet = cleaned[start : end + 1]
    return json.loads(snippet)


def parse_directive(text: str) -> LLMDirective:
    """Parse raw LLM output into an :class:`LLMDirective`."""

    data = extract_json_object(text)
    return LLMDirective.model_validate(data)


def _strip_code_fence(block: str) -> str:
    parts = block.split("```")
    if len(parts) >= 3:
        return parts[1]
    return block.strip("`")


