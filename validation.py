"""Schema validation helpers for MCP requests.

Provides a JSON Schema for MCPTaskRequest and a helper to validate payloads.
"""
from jsonschema import validate, ValidationError


MCP_TASK_SCHEMA = {
    "type": "object",
    "required": ["task_id", "prompt", "provider"],
    "properties": {
        "task_id": {"type": "string"},
        "prompt": {"type": "string"},
        "provider": {"type": "string", "enum": ["openai", "ollama"]},
        "model": {"type": "string"},
        "timeout_seconds": {"type": "integer"},
        "env_overrides": {"type": "object", "additionalProperties": {"type": "string"}}
    }
}


def validate_mcp_request(payload: dict) -> bool:
    """Validate a payload against the MCPTaskRequest schema.

    Raises:
        jsonschema.ValidationError: on invalid payloads with a helpful message.

    Returns:
        True when valid.
    """
    try:
        validate(instance=payload, schema=MCP_TASK_SCHEMA)
    except ValidationError as exc:
        # Re-raise with a clear message for upstream handling
        raise ValidationError(f"Invalid MCPTaskRequest: {exc.message}") from exc

    return True
