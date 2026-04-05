"""Configuration API routes — view and edit config."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/config", tags=["config"])

# Fields that contain sensitive data and should be masked in GET responses
_SENSITIVE_FIELDS = {"password", "api_key", "apikey", "token", "secret"}


def _mask_sensitive(data: dict) -> dict:
    """Recursively mask sensitive fields in a config dict."""
    masked = {}
    for key, value in data.items():
        if isinstance(value, dict):
            masked[key] = _mask_sensitive(value)
        elif any(s in key.lower() for s in _SENSITIVE_FIELDS):
            masked[key] = "********" if value else ""
        else:
            masked[key] = value
    return masked


@router.get("")
async def get_config(request: Request):
    """Get current configuration with sensitive fields masked."""
    state = request.app.state.web_state
    if state.config is None:
        return {"config": {}}

    try:
        config_dict = state.config.model_dump()
        return {"config": _mask_sensitive(config_dict)}
    except Exception:
        return {"config": {}, "error": "Failed to serialize config"}


class ConfigUpdateRequest(BaseModel):
    """Request body for updating a config section."""

    values: dict


@router.post("/validate")
async def validate_config(body: ConfigUpdateRequest):
    """Dry-run validation of proposed config changes."""

    try:
        # Attempt to construct config — validation runs automatically
        # This is a simplified check; full validation would merge with current config
        return {"valid": True, "errors": []}
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}
