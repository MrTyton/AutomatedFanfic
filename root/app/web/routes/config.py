"""Configuration API routes — view and edit config."""

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
    return config_service.get_masked_config_payload(request.app.state.web_state)


@router.get("/secret")
async def get_secret(section: str, key: str, request: Request) -> dict[str, str]:
    """Retrieve the unmasked value of a sensitive configuration field on demand."""
    val, err = config_service.get_unmasked_secret(
        request.app.state.web_state, section, key
    )
    if err is not None or val is None:
        raise HTTPException(status_code=404, detail=err or "Secret not found")
    return {"value": val}


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
    return config_service.read_ini_file_action(request.app.state.web_state, ini_type)


@router.put("/ini/{ini_type}")
async def update_ini_file(ini_type: str, request: Request, body: IniUpdateRequest):
    """Overwrite personal.ini with the supplied content. defaults.ini is packaged and read-only."""
    return config_service.write_ini_file_action(
        request.app.state.web_state, ini_type, body.content
    )
