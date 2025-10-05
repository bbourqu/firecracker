import json
from jsonschema import validate, ValidationError

# Minimal subset of the OpenAPI MCPTaskRequest schema used for unit tests
MCP_TASK_SCHEMA = {
    "type": "object",
    "required": ["task_id", "prompt", "provider"],
    "properties": {
        "task_id": {"type": "string"},
        "prompt": {"type": "string"},
        "provider": {"type": "string", "enum": ["openai", "ollama"]}
    }
}


def test_valid_minimal_payload():
    payload = {"task_id": "t1", "prompt": "Hello", "provider": "ollama"}
    # should not raise
    validate(instance=payload, schema=MCP_TASK_SCHEMA)


def test_missing_task_id_should_fail():
    payload = {"prompt": "Hello", "provider": "ollama"}
    try:
        validate(instance=payload, schema=MCP_TASK_SCHEMA)
        assert False, "ValidationError expected"
    except ValidationError as e:
        assert "'task_id' is a required property" in str(e) or e.validator == 'required'
