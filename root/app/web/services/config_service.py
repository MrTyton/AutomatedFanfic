"""Configuration management, masking, validation, and testing service."""

from pathlib import Path
import time
from typing import Any

from config.ini_resolver import resolve_ini_path, resolve_state_personal_ini
from config.store import ConfigStore, ReloadBehavior
from config.toml_writer import TomlWriter
import ff_logging

lazy import apprise
lazy from config import (
    AppConfig,
    AppriseConfig,
    CalibreConfig,
    ConfigManager,
    EmailConfig,
    ProcessConfig,
    PushbulletConfig,
    RetryConfig,
    WebConfig,
    toml_settings_context,
)
lazy from services import email_client
lazy from web.services.calibre_lookup import get_calibre_client

SENSITIVE_FIELDS = {"password", "api_key", "apikey", "token", "secret"}
MASK = "********"


def mask_sensitive(data: dict) -> dict:
    """Recursively mask sensitive fields in a config dict."""
    masked = {}
    for key, value in data.items():
        if isinstance(value, dict):
            masked[key] = mask_sensitive(value)
        elif any(s in key.lower() for s in SENSITIVE_FIELDS):
            masked[key] = MASK if value else ""
        else:
            masked[key] = value
    return masked


def restore_masked_sensitive(current: dict, incoming: dict) -> dict:
    """Replace masked '********' sensitive values with their existing values."""
    cleaned = {}
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            cleaned[key] = restore_masked_sensitive(current[key], value)
        elif (
            value == MASK
            and any(s in key.lower() for s in SENSITIVE_FIELDS)
            and key in current
        ):
            cleaned[key] = current[key]
        else:
            cleaned[key] = value
    return cleaned


def merge_config_dict(current: dict, updates: dict) -> dict:
    """Deep-merge section dictionaries into a copy of the current config dict."""
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in current.items()}
    cleaned_updates = restore_masked_sensitive(current, updates)
    for key, value in cleaned_updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def annotate_reload_behavior(config_dict: dict) -> dict:
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


def validate_config_changes(state: Any, values: dict) -> dict[str, Any]:
    """Dry-run validation of proposed config changes."""
    if state.config is None:
        return {"valid": False, "errors": ["No config loaded"]}

    try:
        current = state.config.model_dump()
        merged = merge_config_dict(current, values)
        with toml_settings_context(merged):
            AppConfig(**merged)
        return {"valid": True, "errors": []}
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}


def update_config_section_action(
    state: Any, section: str, values: dict
) -> dict[str, Any]:
    """Update a config section, persist to TOML, and apply hot-reloadable changes."""
    if state.config is None:
        return {"applied": False, "error": "No config loaded"}

    config_dict = state.config.model_dump()
    if section not in config_dict or not isinstance(config_dict[section], dict):
        valid_sections = [k for k in config_dict if isinstance(config_dict[k], dict)]
        return {
            "applied": False,
            "error": f"Unknown section '{section}'. Valid: {valid_sections}",
        }

    current_section = config_dict[section]
    cleaned_values = restore_masked_sensitive(current_section, values)

    validated_config = None
    try:
        if isinstance(state.config, AppConfig):
            proposed = merge_config_dict(config_dict, {section: cleaned_values})
            with toml_settings_context(proposed):
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

    classified = ConfigStore.classify_changes(section, cleaned_values)
    results = {"hot": [], "service_restart": [], "app_restart": []}

    if classified[ReloadBehavior.HOT] and state.config_store is not None:
        hot_updates = {}
        for field_name, value in classified[ReloadBehavior.HOT].items():
            key = f"{section}.{field_name}"
            hot_updates[key] = value
            results["hot"].append(field_name)
        state.config_store.update_many(hot_updates)

    if state.config_path:
        try:
            writer = TomlWriter(state.config_path)
            writer.write_section(section, cleaned_values)
        except Exception as e:
            return {"applied": False, "error": f"Failed to write config: {e}"}
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


def test_config_section_action(
    app_state: Any, section: str, incoming_values: dict[str, Any]
) -> dict[str, Any]:
    """Test connectivity or validate configuration parameters for a specific section."""
    state = getattr(app_state, "web_state", app_state)
    norm_section = section.strip().lower()
    t0 = time.perf_counter()

    config_dict = state.config.model_dump() if state.config is not None else {}
    current_sec = config_dict.get(norm_section, {})
    values = restore_masked_sensitive(current_sec, incoming_values)

    if norm_section == "email":
        server = values.get("server") or current_sec.get("server")
        user = (
            values.get("email")
            or values.get("user")
            or current_sec.get("email")
            or current_sec.get("user")
        )
        password = values.get("password") or current_sec.get("password")
        mailbox = values.get("mailbox") or current_sec.get("mailbox") or "INBOX"

        if not server or not user or not password:
            return {
                "ok": False,
                "message": "Email test requires server, email/username, and password",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }

        try:
            probe_res = email_client.probe_imap_connection(
                str(server), str(user), str(password), str(mailbox), timeout=5.0
            )
            unread_count = probe_res["unread_count"]
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": True,
                "message": f"Connected to IMAP server ({server}, mailbox '{mailbox}', {unread_count} unread)",
                "latency_ms": latency,
            }
        except Exception as exc:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": False,
                "message": f"IMAP connection failed: {exc}",
                "latency_ms": latency,
            }

    if norm_section == "calibre":
        calibre_path = values.get("path") or current_sec.get("path") or ""
        if not calibre_path:
            return {
                "ok": False,
                "message": "Calibre path is required",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        try:
            client = get_calibre_client(app_state)
            if client is not None:
                version = (
                    client.get_version()
                    if hasattr(client, "get_version")
                    else "connected"
                )
                latency = round((time.perf_counter() - t0) * 1000, 1)
                return {
                    "ok": True,
                    "message": f"Calibre library connected ({version})",
                    "latency_ms": latency,
                }
            cpath = Path(str(calibre_path))
            if cpath.exists():
                latency = round((time.perf_counter() - t0) * 1000, 1)
                return {
                    "ok": True,
                    "message": f"Calibre path exists: {cpath}",
                    "latency_ms": latency,
                }
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": False,
                "message": f"Calibre path does not exist: {cpath}",
                "latency_ms": latency,
            }
        except Exception as exc:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": False,
                "message": f"Calibre test failed: {exc}",
                "latency_ms": latency,
            }

    if norm_section == "apprise":
        raw_urls = values.get("urls") or current_sec.get("urls") or []
        urls = [raw_urls] if isinstance(raw_urls, str) else list(raw_urls)
        if not urls:
            return {
                "ok": False,
                "message": "No Apprise notification URLs configured",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        try:
            ap = apprise.Apprise()
            count = 0
            for u in urls:
                if u and ap.add(str(u)):
                    count += 1
            latency = round((time.perf_counter() - t0) * 1000, 1)
            if count > 0:
                return {
                    "ok": True,
                    "message": f"Successfully parsed {count} Apprise notification endpoint(s)",
                    "latency_ms": latency,
                }
            return {
                "ok": False,
                "message": "None of the configured Apprise URLs could be parsed as valid endpoints",
                "latency_ms": latency,
            }
        except Exception as exc:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": False,
                "message": f"Apprise validation error: {exc}",
                "latency_ms": latency,
            }

    if norm_section == "pushbullet":
        api_key = values.get("api_key") or current_sec.get("api_key")
        if not api_key:
            return {
                "ok": False,
                "message": "Pushbullet api_key is required",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        try:
            ap = apprise.Apprise()
            if ap.add(f"pbul://{api_key}"):
                latency = round((time.perf_counter() - t0) * 1000, 1)
                return {
                    "ok": True,
                    "message": "Pushbullet configuration valid",
                    "latency_ms": latency,
                }
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": False,
                "message": "Pushbullet api_key format is invalid",
                "latency_ms": latency,
            }
        except Exception as exc:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": False,
                "message": f"Pushbullet validation error: {exc}",
                "latency_ms": latency,
            }

    section_models = {
        "process": ProcessConfig,
        "retry": RetryConfig,
        "web": WebConfig,
    }
    if norm_section in section_models:
        try:
            model_cls = section_models[norm_section]
            merged_sec = {**current_sec, **values}
            model_cls(**merged_sec)
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": True,
                "message": f"[{norm_section}] configuration parameters are valid",
                "latency_ms": latency,
            }
        except Exception as exc:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": False,
                "message": f"[{norm_section}] validation error: {exc}",
                "latency_ms": latency,
            }

    latency = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "ok": True,
        "message": f"Section [{norm_section}] validated successfully",
        "latency_ms": latency,
    }


def resolve_config_ini_path(state: Any, ini_type: str) -> tuple[str | None, str | None]:
    """Resolve the filesystem path for personal.ini or defaults.ini."""
    if state.config is None:
        return None, "No config loaded"
    if ini_type == "personal":
        path = resolve_state_personal_ini(state)
        if not path:
            return None, "No path configured for personal.ini"
    elif ini_type == "defaults":
        if getattr(state, "config_store", None):
            path = state.config_store.get_resolved_default_ini()
        else:
            raw_path = state.config.calibre.default_ini
            path = resolve_ini_path(raw_path, "defaults.ini")
        if not path:
            return None, "No defaults.ini found in package or configuration"
    else:
        return None, f"Unknown ini type '{ini_type}'. Valid: personal, defaults"

    return path, None


def get_masked_config_payload(state: Any) -> dict[str, Any]:
    """Build the masked configuration and reload behavior payload for GET /api/config."""
    if state.config is None:
        return {"config": {}}

    try:
        config_dict = state.config.model_dump()
        masked = mask_sensitive(config_dict)
        return {
            "config": masked,
            "reload_map": annotate_reload_behavior(config_dict),
        }
    except Exception:
        return {"config": {}, "error": "Failed to serialize config"}


def get_unmasked_secret(
    state: Any, section: str, key: str
) -> tuple[str | None, str | None]:
    """Retrieve the unmasked value of a sensitive configuration field, or (None, error_detail)."""
    if state.config is None:
        return None, "No config loaded"

    config_dict = state.config.model_dump()
    sec_data = config_dict.get(section)
    if not isinstance(sec_data, dict):
        return None, f"Section '{section}' not found"

    if key not in sec_data:
        return None, f"Key '{key}' not found in section '{section}'"

    val = sec_data.get(key)
    return (str(val) if val is not None else ""), None


def read_ini_file_action(state: Any, ini_type: str) -> dict[str, Any]:
    """Read the raw content of personal.ini or defaults.ini."""
    path, err = resolve_config_ini_path(state, ini_type)
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


def write_ini_file_action(state: Any, ini_type: str, content: str) -> dict[str, Any]:
    """Overwrite personal.ini with the supplied content (defaults.ini is read-only)."""
    if ini_type == "defaults":
        return {
            "applied": False,
            "error": "defaults.ini is packaged and updated automatically with FanFicFare releases. Put personal overrides in personal.ini.",
        }

    path, err = resolve_config_ini_path(state, ini_type)
    if err or path is None:
        return {"applied": False, "error": err}

    ini_path = Path(path)
    try:
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text(content, encoding="utf-8")
        return {"applied": True}
    except OSError:
        return {"applied": False, "error": "Failed to write file"}
