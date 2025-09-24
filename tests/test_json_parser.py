from remote_browser_tool.llm.json_parser import extract_json_object, parse_directive
from remote_browser_tool.models import DirectiveStatus


def test_extract_json_object_from_code_fence():
    text = """```json\n{"status": "finished", "actions": []}\n```"""
    result = extract_json_object(text)
    assert result["status"] == "finished"
    assert result["actions"] == []


def test_parse_directive_round_trip():
    directive = parse_directive('{"status": "wait", "actions": [], "memory_to_write": []}')
    assert directive.status == DirectiveStatus.WAIT
    assert directive.actions == []
    assert directive.memory_to_write == []


