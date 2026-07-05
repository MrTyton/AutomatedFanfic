"""Configuration API routes — view and edit config."""

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from config.config_store import ConfigStore, ReloadBehavior, FIELD_RELOAD_MAP
from config.toml_writer import TomlWriter

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


def _annotate_reload_behavior(config_dict: dict) -> dict:
    """Add reload_behavior annotation to each section's fields."""
    annotated = {}
    for section, values in config_dict.items():
        if isinstance(values, dict):
            section_annotated = {}
            for field_name, value in values.items():
                behavior = ConfigStore.get_reload_behavior(section, field_name)
                section_annotated[field_name] = {
                    "value": value,
                    "reload_behavior": behavior.value,
                }
            annotated[section] = section_annotated
        else:
            behavior = ConfigStore.get_reload_behavior("", section)
            annotated[section] = {
                "value": values,
                "reload_behavior": behavior.value,
            }
    return annotated


@router.get("")
async def get_config(request: Request):
    """Get current configuration with sensitive fields masked and reload annotations."""
    state = request.app.state.web_state
    if state.config is None:
        return {"config": {}}

    try:
        config_dict = state.config.model_dump()
        masked = _mask_sensitive(config_dict)
        return {"config": masked, "reload_map": _annotate_reload_behavior(config_dict)}
    except Exception:
        return {"config": {}, "error": "Failed to serialize config"}


class ConfigUpdateRequest(BaseModel):
    """Request body for updating a config section."""

    values: dict


@router.post("/validate")
async def validate_config(request: Request, body: ConfigUpdateRequest):
    """Dry-run validation of proposed config changes."""
    state = request.app.state.web_state
    if state.config is None:
        return {"valid": False, "errors": ["No config loaded"]}

    try:
        current = state.config.model_dump()
        merged = {**current, **body.values}
        from models.config_models import AppConfig

        AppConfig(**merged)
        return {"valid": True, "errors": []}
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}


@router.put("/{section}")
async def update_config_section(
    section: str, request: Request, body: ConfigUpdateRequest
):
    """Update a config section. Classifies changes by reload behaviour.

    Hot-reloadable changes are applied immediately via the shared ConfigStore.
    All changes are persisted to TOML. Service/app-restart fields are flagged
    in the response so the UI can inform the user.
    """
    state = request.app.state.web_state

    if state.config is None:
        return {"applied": False, "error": "No config loaded"}

    config_dict = state.config.model_dump()
    if section not in config_dict:
        valid_sections = [k for k in config_dict if isinstance(config_dict[k], dict)]
        return {
            "applied": False,
            "error": f"Unknown section '{section}'. Valid: {valid_sections}",
        }

    # Classify changes by reload behaviour
    classified = ConfigStore.classify_changes(section, body.values)
    results = {"hot": [], "service_restart": [], "app_restart": []}

    # Apply hot-reloadable changes immediately
    if classified[ReloadBehavior.HOT] and state.config_store is not None:
        hot_updates = {}
        for field_name, value in classified[ReloadBehavior.HOT].items():
            key = f"{section}.{field_name}"
            hot_updates[key] = value
            results["hot"].append(field_name)
        state.config_store.update_many(hot_updates)

    # Write ALL changes to TOML so the file stays in sync
    if state.config_path:
        try:
            writer = TomlWriter(state.config_path)
            writer.write_section(section, body.values)
        except Exception as e:
            return {"applied": False, "error": f"Failed to write config: {e}"}

    for field_name in classified[ReloadBehavior.SERVICE_RESTART]:
        results["service_restart"].append(field_name)
    for field_name in classified[ReloadBehavior.APP_RESTART]:
        results["app_restart"].append(field_name)

    return {
        "applied": True,
        "results": results,
        "needs_service_restart": bool(results["service_restart"]),
        "needs_app_restart": bool(results["app_restart"]),
    }


@router.get("/reload-map")
async def get_reload_map():
    """Return the full field → reload-behaviour mapping for the UI."""
    return {key: behavior.value for key, behavior in FIELD_RELOAD_MAP.items()}


# ── INI file endpoints ──────────────────────────────────────────


class IniUpdateRequest(BaseModel):
    """Request body for updating an INI file."""

    content: str


def _resolve_ini_path(state, ini_type: str) -> tuple[str | None, str | None]:
    """Resolve the filesystem path for the given ini_type.

    Args:
        state: The WebState instance holding the loaded config.
        ini_type: Either ``"personal"`` (personal.ini) or ``"defaults"``
            (defaults.ini).

    Returns:
        A ``(path, error)`` tuple.  Exactly one of the two values will be
        non-``None``: ``path`` on success, ``error`` when the type is
        unknown, no config is loaded, or the path is not configured.
    """
    if state.config is None:
        return None, "No config loaded"
    # Use explicit branches so the path is provably derived from server config,
    # not from the user-supplied ini_type string.
    if ini_type == "personal":
        path = state.config.calibre.personal_ini
    elif ini_type == "defaults":
        path = state.config.calibre.default_ini
    else:
        return None, f"Unknown ini type '{ini_type}'. Valid: personal, defaults"
    if not path:
        return None, f"No path configured for {ini_type}.ini"
    return path, None


@router.get("/ini/{ini_type}")
async def get_ini_file(ini_type: str, request: Request):
    """Return the raw content of personal.ini or defaults.ini."""
    state = request.app.state.web_state
    path, err = _resolve_ini_path(state, ini_type)
    if err:
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
    """Overwrite personal.ini or defaults.ini with the supplied content."""
    state = request.app.state.web_state
    path, err = _resolve_ini_path(state, ini_type)
    if err:
        return {"applied": False, "error": err}

    ini_path = Path(path)
    try:
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text(body.content, encoding="utf-8")
        return {"applied": True}
    except OSError:
        return {"applied": False, "error": "Failed to write file"}
