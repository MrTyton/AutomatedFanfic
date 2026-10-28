"""Configuration API routes — view and edit config."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.config_store import ConfigStore, ReloadBehavior, FIELD_RELOAD_MAP
from config.toml_writer import TomlWriter
from utils import ff_logging
from utils.system_utils import resolve_ini_path

lazy from models.config_models import (
    AppConfig,
    AppriseConfig,
    CalibreConfig,
    ConfigManager,
    EmailConfig,
    ProcessConfig,
    PushbulletConfig,
    RetryConfig,
    WebConfig,
)

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


def _restore_masked_sensitive(current: dict, incoming: dict) -> dict:
    """Replace masked '********' sensitive values with their existing values."""
    cleaned = {}
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            cleaned[key] = _restore_masked_sensitive(current[key], value)
        elif (
            value == "********"
            and any(s in key.lower() for s in _SENSITIVE_FIELDS)
            and key in current
        ):
            cleaned[key] = current[key]
        else:
            cleaned[key] = value
    return cleaned


def _merge_config_dict(current: dict, updates: dict) -> dict:
    """Deep-merge section dictionaries into a copy of the current config dict."""
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in current.items()}
    cleaned_updates = _restore_masked_sensitive(current, updates)
    for key, value in cleaned_updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


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
        merged = _merge_config_dict(current, body.values)
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
    if section not in config_dict or not isinstance(config_dict[section], dict):
        valid_sections = [k for k in config_dict if isinstance(config_dict[k], dict)]
        return {
            "applied": False,
            "error": f"Unknown section '{section}'. Valid: {valid_sections}",
        }

    # Restore masked sensitive fields so '********' from the UI never overwrites real secrets
    current_section = config_dict[section]
    cleaned_values = _restore_masked_sensitive(current_section, body.values)

    # Validate merged configuration with AppConfig (or section model if state.config is a mock)
    validated_config = None
    try:
        if isinstance(state.config, AppConfig):
            proposed = _merge_config_dict(config_dict, {section: cleaned_values})
            validated_config = AppConfig(**proposed)
        else:
            section_models = {
                "email": EmailConfig,
                "calibre": CalibreConfig,
                "pushbullet": PushbulletConfig,
                "apprise": AppriseConfig,
                "retry": RetryConfig,
                "process": ProcessConfig,
                "web": WebConfig,
            }
            if section in section_models:
                model_cls = section_models[section]
                dummy = model_cls.model_construct(**current_section)
                for k, v in cleaned_values.items():
                    model_cls.__pydantic_validator__.validate_assignment(dummy, k, v)
    except Exception as e:
        return {"applied": False, "error": f"Validation error: {e}"}

    # Classify changes by reload behaviour
    classified = ConfigStore.classify_changes(section, cleaned_values)
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
            writer.write_section(section, cleaned_values)
        except Exception as e:
            return {"applied": False, "error": f"Failed to write config: {e}"}
        # Reload the in-memory config so GET /api/config immediately reflects the new values
        try:
            state.config = ConfigManager.load_config(
                state.config_path, force_reload=True
            )
        except Exception:
            if validated_config is not None:
                state.config = validated_config
    elif validated_config is not None:
        state.config = validated_config

    for field_name in classified[ReloadBehavior.SERVICE_RESTART]:
        results["service_restart"].append(field_name)
    for field_name in classified[ReloadBehavior.APP_RESTART]:
        results["app_restart"].append(field_name)

    # Auto-restart web server when any web.* SERVICE_RESTART field changed
    if results["service_restart"] and section == "web":
        web_restart_event = getattr(state, "web_restart_event", None)
        if web_restart_event is not None:
            web_restart_event.set()
            ff_logging.log_debug("WebServer: restart requested via web_restart_event")

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
        raw_path = state.config.calibre.personal_ini
        default_filename = "personal.ini"
        if not raw_path:
            return None, "No path configured for personal.ini"
        path = resolve_ini_path(raw_path, default_filename)
    elif ini_type == "defaults":
        raw_path = state.config.calibre.default_ini
        default_filename = "defaults.ini"
        path = resolve_ini_path(raw_path, default_filename)
        if not path:
            return None, "No defaults.ini found in package or configuration"
    else:
        return None, f"Unknown ini type '{ini_type}'. Valid: personal, defaults"

    return path, None


@router.get("/ini/{ini_type}")
async def get_ini_file(ini_type: str, request: Request):
    """Return the raw content of personal.ini or defaults.ini."""
    state = request.app.state.web_state
    path, err = _resolve_ini_path(state, ini_type)
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
    path, err = _resolve_ini_path(state, ini_type)
    if err or path is None:
        return {"applied": False, "error": err}

    ini_path = Path(path)
    try:
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text(body.content, encoding="utf-8")
        return {"applied": True}
    except OSError:
        return {"applied": False, "error": "Failed to write file"}
