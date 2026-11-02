"""Configuration API routes — view and edit config."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.store import FIELD_RELOAD_MAP
from web.services import config_service

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdateRequest(BaseModel):
    """Request body for updating a config section."""

    values: dict


class ConfigTestRequest(BaseModel):
    """Request body for testing a config section."""

    values: dict[str, Any] = {}


class IniUpdateRequest(BaseModel):
    """Request body for updating an INI file."""

    content: str


@router.get("")
async def get_config(request: Request):
    """Get current configuration with sensitive fields masked and reload annotations."""
    state = request.app.state.web_state
    if state.config is None:
        return {"config": {}}

    try:
        config_dict = state.config.model_dump()
        masked = config_service.mask_sensitive(config_dict)
        return {
            "config": masked,
            "reload_map": config_service.annotate_reload_behavior(config_dict),
        }
    except Exception:
        return {"config": {}, "error": "Failed to serialize config"}


@router.get("/secret")
async def get_secret(section: str, key: str, request: Request) -> dict[str, str]:
    """Retrieve the unmasked value of a sensitive configuration field on demand."""
    state = request.app.state.web_state
    if state.config is None:
        raise HTTPException(status_code=404, detail="No config loaded")

    config_dict = state.config.model_dump()
    sec_data = config_dict.get(section)
    if not isinstance(sec_data, dict):
        raise HTTPException(status_code=404, detail=f"Section '{section}' not found")

    if key not in sec_data:
        raise HTTPException(
            status_code=404, detail=f"Key '{key}' not found in section '{section}'"
        )

    val = sec_data.get(key)
    return {"value": str(val) if val is not None else ""}


@router.post("/validate")
async def validate_config(request: Request, body: ConfigUpdateRequest):
    """Dry-run validation of proposed config changes."""
    return config_service.validate_config_changes(
        request.app.state.web_state, body.values
    )


@router.put("/{section}")
async def update_config_section(
    section: str, request: Request, body: ConfigUpdateRequest
):
    """Update a config section and classify changes by reload behaviour."""
    return config_service.update_config_section_action(
        request.app.state.web_state, section, body.values
    )


@router.post("/{section}/test")
async def test_config_section(section: str, request: Request, body: ConfigTestRequest):
    """Test connectivity or validate configuration parameters for a specific section."""
    return config_service.test_config_section_action(
        request.app.state, section, body.values
    )


@router.get("/reload-map")
async def get_reload_map():
    """Return the full field → reload-behaviour mapping for the UI."""
    return {key: behavior.value for key, behavior in FIELD_RELOAD_MAP.items()}


@router.get("/ini/{ini_type}")
async def get_ini_file(ini_type: str, request: Request):
    """Return the raw content of personal.ini or defaults.ini."""
    state = request.app.state.web_state
    path, err = config_service.resolve_config_ini_path(state, ini_type)
    if err or path is None:
        return {"content": None, "path": None, "error": err}

    ini_path = Path(path)
    if not ini_path.is_file():
        return {"content": "", "path": path, "error": None}

    try:
        content = ini_path.read_text(encoding="utf-8")
        return {"content": content, "path": path, "error": None}
    except OSError:
        return {"content": None, "path": path, "error": "Failed to read file"}


@router.put("/ini/{ini_type}")
async def update_ini_file(ini_type: str, request: Request, body: IniUpdateRequest):
    """Overwrite personal.ini with the supplied content. defaults.ini is packaged and read-only."""
    if ini_type == "defaults":
        return {
            "applied": False,
            "error": "defaults.ini is packaged and updated automatically with FanFicFare releases. Put personal overrides in personal.ini.",
        }

    state = request.app.state.web_state
    path, err = config_service.resolve_config_ini_path(state, ini_type)
    if err or path is None:
        return {"applied": False, "error": err}

    ini_path = Path(path)
    try:
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text(body.content, encoding="utf-8")
        return {"applied": True}
    except OSError:
        return {"applied": False, "error": "Failed to write file"}
