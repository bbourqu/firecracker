import pytest
from validation import validate_mcp_request
from jsonschema import ValidationError


def test_validate_valid_payload():
    payload = {"task_id": "t1", "prompt": "Do work", "provider": "ollama"}
    assert validate_mcp_request(payload) is True


def test_validate_invalid_payload():
    payload = {"prompt": "No id", "provider": "ollama"}
    with pytest.raises(ValidationError):
        validate_mcp_request(payload)
