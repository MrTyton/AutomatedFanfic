"""Shared configuration store for cross-process hot-reload.

Wraps a multiprocessing Manager dict to share hot-reloadable config values
between all processes. Services read from this store each iteration instead
of their local config copies.
"""

from collections.abc import Callable, MutableMapping
from enum import Enum
from typing import TYPE_CHECKING

lazy from fanficfare import configurable
from config.ini_resolver import (
    build_fff_configuration,
    clear_ini_cache,
    read_ini_file_cached,
    resolve_ini_path,
)

if TYPE_CHECKING:
    from config.schemas.app import AppConfig


class ReloadBehavior(str, Enum):
    """How the system reacts when a config field changes."""

    HOT = "hot"  # Updated immediately via shared dict — no interruption
    SERVICE_RESTART = "service_restart"  # Web server restarts automatically
    APP_RESTART = "app_restart"  # Requires restarting the application process


# Exhaustive map of dotted field keys → reload behaviour
FIELD_RELOAD_MAP: dict[str, ReloadBehavior] = {
    # ── Hot-reloadable ──────────────────────────────────────────
    # Polling / retry behaviour
    "email.sleep_time": ReloadBehavior.HOT,
    "email.disabled_sites": ReloadBehavior.HOT,
    # Email credentials — email_watcher re-connects on next poll cycle
    "email.email": ReloadBehavior.HOT,
    "email.password": ReloadBehavior.HOT,
    "email.server": ReloadBehavior.HOT,
    "email.mailbox": ReloadBehavior.HOT,
    "email.imap_idle": ReloadBehavior.HOT,
    # Calibre — workers refresh before each calibredb call
    "calibre.update_method": ReloadBehavior.HOT,
    "calibre.metadata_preservation_mode": ReloadBehavior.HOT,
    "calibre.update_only": ReloadBehavior.HOT,
    "calibre.path": ReloadBehavior.HOT,
    "calibre.username": ReloadBehavior.HOT,
    "calibre.password": ReloadBehavior.HOT,
    "calibre.default_ini": ReloadBehavior.HOT,
    "calibre.personal_ini": ReloadBehavior.HOT,
    # Notifications — wrapper rebuilds Apprise client on hash change
    "pushbullet.enabled": ReloadBehavior.HOT,
    "pushbullet.api_key": ReloadBehavior.HOT,
    "pushbullet.device": ReloadBehavior.HOT,
    "apprise.urls": ReloadBehavior.HOT,
    # Retry logic
    "retry.max_normal_retries": ReloadBehavior.HOT,
    "retry.hail_mary_enabled": ReloadBehavior.HOT,
    "retry.hail_mary_wait_hours": ReloadBehavior.HOT,
    "retry.resume_uncompleted_on_startup": ReloadBehavior.HOT,
    # Process monitor — ProcessManager reads these each tick
    "process.max_workers": ReloadBehavior.HOT,
    "process.shutdown_timeout": ReloadBehavior.HOT,
    "process.health_check_interval": ReloadBehavior.HOT,
    "process.max_restart_attempts": ReloadBehavior.HOT,
    # ── Service restart (web server auto-restarts) ───────────────
    "web.enabled": ReloadBehavior.SERVICE_RESTART,
    "web.host": ReloadBehavior.SERVICE_RESTART,
    "web.port": ReloadBehavior.SERVICE_RESTART,
    "web.history_db_path": ReloadBehavior.SERVICE_RESTART,
    "web.log_file_path": ReloadBehavior.SERVICE_RESTART,
    # ── Requires Application Restart ────────────────────────────
    "process.restart_delay": ReloadBehavior.APP_RESTART,
    "process.enable_monitoring": ReloadBehavior.APP_RESTART,
    "process.worker_timeout": ReloadBehavior.APP_RESTART,
    "process.signal_timeout": ReloadBehavior.APP_RESTART,
}


class ConfigStore:
    """Thread-safe and process-safe configuration store backed by a Manager dict."""

    def __init__(self, shared_dict: MutableMapping[str, object] | None = None) -> None:
        """Initialize the store with an optional shared dictionary."""
        self._store: MutableMapping[str, object] = (
            shared_dict if shared_dict is not None else {}
        )

    def initialize_from_config(self, config: AppConfig) -> None:
        """Populate the store from an AppConfig object."""
        self._store["email.sleep_time"] = config.email.sleep_time
        self._store["email.disabled_sites"] = list(config.email.disabled_sites)
        self._store["email.email"] = config.email.email
        self._store["email.password"] = config.email.password
        self._store["email.server"] = config.email.server
        self._store["email.mailbox"] = config.email.mailbox
        self._store["email.imap_idle"] = config.email.imap_idle

        self._store["calibre.update_method"] = config.calibre.update_method
        self._store["calibre.metadata_preservation_mode"] = (
            config.calibre.metadata_preservation_mode.value
            if hasattr(config.calibre.metadata_preservation_mode, "value")
            else config.calibre.metadata_preservation_mode
        )
        self._store["calibre.update_only"] = config.calibre.update_only
        self._store["calibre.path"] = config.calibre.path
        self._store["calibre.username"] = config.calibre.username
        self._store["calibre.password"] = config.calibre.password
        self._store["calibre.default_ini"] = config.calibre.default_ini
        self._store["calibre.personal_ini"] = config.calibre.personal_ini

        self._store["pushbullet.enabled"] = config.pushbullet.enabled
        self._store["pushbullet.api_key"] = config.pushbullet.api_key
        self._store["pushbullet.device"] = config.pushbullet.device
        self._store["apprise.urls"] = list(config.apprise.urls)

        self._store["retry.max_normal_retries"] = config.retry.max_normal_retries
        self._store["retry.hail_mary_enabled"] = config.retry.hail_mary_enabled
        self._store["retry.hail_mary_wait_hours"] = config.retry.hail_mary_wait_hours
        self._store["retry.resume_uncompleted_on_startup"] = (
            config.retry.resume_uncompleted_on_startup
        )

        self._store["process.health_check_interval"] = (
            config.process.health_check_interval
        )
        self._store["process.shutdown_timeout"] = config.process.shutdown_timeout
        self._store["process.max_restart_attempts"] = (
            config.process.max_restart_attempts
        )
        self._store["process.max_workers"] = config.process.max_workers
        self._store["__version__"] = 1

    def update_from_config(self, config: AppConfig) -> None:
        """Alias for initialize_from_config."""
        self.initialize_from_config(config)

    def get(self, key: str, default: object = None) -> object:
        """Retrieve a value by dotted key path."""
        try:
            return self._store.get(key, default)
        except Exception:
            return default

    def set(self, key: str, value: object) -> None:
        """Set a value by dotted key path."""
        self.update(key, value)

    def update(self, key: str, value: object) -> None:
        """Update a single key and increment store version."""
        self._store[key] = value
        try:
            curr_ver = self._store.get("__version__", 0)
            self._store["__version__"] = (
                curr_ver if isinstance(curr_ver, int) else 0
            ) + 1
        except Exception:
            pass

    def update_many(self, updates: dict[str, object]) -> None:
        """Update multiple keys and increment store version."""
        for key, value in updates.items():
            self._store[key] = value
        try:
            curr_ver = self._store.get("__version__", 0)
            self._store["__version__"] = (
                curr_ver if isinstance(curr_ver, int) else 0
            ) + 1
        except Exception:
            pass

    def get_version(self) -> int | None:
        """Return the current configuration version counter, if tracked."""
        val = self.get("__version__")
        return val if isinstance(val, int) else None

    def get_all(self) -> dict[str, object]:
        """Return a snapshot of all hot-reloadable values."""
        try:
            data = dict(self._store)
            data.pop("__version__", None)
            return data
        except Exception:
            return {}

    def as_dict(self) -> dict[str, object]:
        """Return a snapshot of the current store contents as a regular dict."""
        return self.get_all()

    # ── FanFicFare INI & Configuration Helpers ───────────────────

    def get_resolved_default_ini(self) -> str:
        """Return the resolved path to defaults.ini (or packaged fallback)."""
        raw = (
            self.get("calibre.default_ini")
            or self.get("fanficfare.default_ini")
            or self.get("default_ini")
        )
        res = resolve_ini_path(raw if isinstance(raw, str) else None, "defaults.ini")
        return res or ""

    def get_resolved_personal_ini(self) -> str:
        """Return the resolved path to personal.ini (or empty string if not configured)."""
        raw = (
            self.get("calibre.personal_ini")
            or self.get("fanficfare.personal_ini")
            or self.get("personal_ini")
        )
        return (
            resolve_ini_path(raw, "personal.ini")
            if isinstance(raw, str) and raw
            else ""
        ) or ""

    def get_fff_configuration(self, url: str) -> configurable.Configuration:
        """Return a FanFicFare Configuration loaded with site sections and INI files."""
        return build_fff_configuration(
            url,
            default_ini_path=self.get_resolved_default_ini(),
            personal_ini_path=self.get_resolved_personal_ini(),
        )

    def get_fff_get_configuration_callable(
        self,
    ) -> Callable[[str], configurable.Configuration]:
        """Return a callable(url: str) -> Configuration for use with fanficfare.geturls.GetURLs."""
        return self.get_fff_configuration

    # ── Classification helpers ──────────────────────────────────

    @staticmethod
    def get_reload_behavior(section: str, field_name: str) -> ReloadBehavior:
        """Return the reload behaviour for a ``section.field`` pair."""
        if not section:
            key = field_name
        else:
            key = f"{section}.{field_name}"
        return FIELD_RELOAD_MAP.get(key, ReloadBehavior.APP_RESTART)

    @staticmethod
    def classify_changes(
        section: str, changes: dict[str, object]
    ) -> dict[ReloadBehavior, dict[str, object]]:
        """Split *changes* into buckets by reload behaviour."""
        classified: dict[ReloadBehavior, dict[str, object]] = {
            ReloadBehavior.HOT: {},
            ReloadBehavior.SERVICE_RESTART: {},
            ReloadBehavior.APP_RESTART: {},
        }
        for field_name, value in changes.items():
            behavior = ConfigStore.get_reload_behavior(section, field_name)
            classified[behavior][field_name] = value
        return classified


__all__ = [
    "ReloadBehavior",
    "FIELD_RELOAD_MAP",
    "ConfigStore",
    "read_ini_file_cached",
    "clear_ini_cache",
]
