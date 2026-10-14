"""Shared configuration store for cross-process hot-reload.

Wraps a multiprocessing Manager dict to share hot-reloadable config values
between all processes. Services read from this store each iteration instead
of their local config copies.
"""

from enum import Enum
from typing import Any


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
    # Process monitor — ProcessManager reads these each tick
    "process.shutdown_timeout": ReloadBehavior.HOT,
    "process.health_check_interval": ReloadBehavior.HOT,
    "process.max_restart_attempts": ReloadBehavior.HOT,
    # ── Service restart (web server auto-restarts) ───────────────
    "web.enabled": ReloadBehavior.SERVICE_RESTART,
    "web.host": ReloadBehavior.SERVICE_RESTART,
    "web.port": ReloadBehavior.SERVICE_RESTART,
    # ── App restart (requires restarting the application) ────────
    # Queue topology cannot be rebuilt at runtime.
    "max_workers": ReloadBehavior.HOT,
}


class ConfigStore:
    """Cross-process shared configuration store for hot-reloadable fields.

    Initialised from an AppConfig at startup and passed to every process/thread.
    Services call ``store.get("email.sleep_time")`` on each loop iteration so
    they pick up changes made via the web dashboard without restarting.
    """

    def __init__(self, shared_dict=None):
        """Accepts an ``mp.Manager().dict()`` for production or a plain dict for tests."""
        self._store = shared_dict if shared_dict is not None else {}

    # ── Bootstrap ───────────────────────────────────────────────

    def initialize_from_config(self, config) -> None:
        """Populate the store from an AppConfig object."""
        # ── Email ──────────────────────────────────────────────
        self._store["email.sleep_time"] = config.email.sleep_time
        self._store["email.disabled_sites"] = list(config.email.disabled_sites)
        self._store["email.email"] = config.email.email
        self._store["email.password"] = config.email.password
        self._store["email.server"] = config.email.server
        self._store["email.mailbox"] = config.email.mailbox
        self._store["email.imap_idle"] = config.email.imap_idle
        # ── Calibre ────────────────────────────────────────────
        self._store["calibre.update_method"] = config.calibre.update_method
        self._store["calibre.metadata_preservation_mode"] = (
            config.calibre.metadata_preservation_mode.value
            if hasattr(config.calibre.metadata_preservation_mode, "value")
            else config.calibre.metadata_preservation_mode
        )
        self._store["calibre.path"] = config.calibre.path
        self._store["calibre.username"] = config.calibre.username
        self._store["calibre.password"] = config.calibre.password
        self._store["calibre.default_ini"] = config.calibre.default_ini
        self._store["calibre.personal_ini"] = config.calibre.personal_ini
        # ── Notifications ──────────────────────────────────────
        self._store["pushbullet.enabled"] = config.pushbullet.enabled
        self._store["pushbullet.api_key"] = config.pushbullet.api_key
        self._store["pushbullet.device"] = config.pushbullet.device
        self._store["apprise.urls"] = list(config.apprise.urls)
        # ── Retry ──────────────────────────────────────────────
        self._store["retry.max_normal_retries"] = config.retry.max_normal_retries
        self._store["retry.hail_mary_enabled"] = config.retry.hail_mary_enabled
        self._store["retry.hail_mary_wait_hours"] = config.retry.hail_mary_wait_hours
        # ── Process monitor ────────────────────────────────────
        self._store[
            "process.health_check_interval"
        ] = config.process.health_check_interval
        self._store["process.shutdown_timeout"] = config.process.shutdown_timeout
        self._store[
            "process.max_restart_attempts"
        ] = config.process.max_restart_attempts

    # ── Read ────────────────────────────────────────────────────

    def get(self, key: str, default=None):
        """Get a config value by its dotted key (e.g. ``email.sleep_time``)."""
        try:
            return self._store.get(key, default)
        except Exception:
            return default

    def get_all(self) -> dict:
        """Return a snapshot of all hot-reloadable values."""
        try:
            return dict(self._store)
        except Exception:
            return {}

    # ── Write ───────────────────────────────────────────────────

    def update(self, key: str, value: Any) -> None:
        self._store[key] = value

    def update_many(self, updates: dict[str, Any]) -> None:
        for key, value in updates.items():
            self._store[key] = value

    # ── Classification helpers ──────────────────────────────────

    @staticmethod
    def get_reload_behavior(section: str, field_name: str) -> ReloadBehavior:
        """Return the reload behaviour for a ``section.field`` pair."""
        key = f"{section}.{field_name}" if section else field_name
        return FIELD_RELOAD_MAP.get(key, ReloadBehavior.APP_RESTART)

    @staticmethod
    def classify_changes(
        section: str, changes: dict
    ) -> dict[ReloadBehavior, dict[str, Any]]:
        """Split *changes* into buckets by reload behaviour."""
        classified: dict[ReloadBehavior, dict[str, Any]] = {
            ReloadBehavior.HOT: {},
            ReloadBehavior.SERVICE_RESTART: {},
            ReloadBehavior.APP_RESTART: {},
        }
        for field_name, value in changes.items():
            behavior = ConfigStore.get_reload_behavior(section, field_name)
            classified[behavior][field_name] = value
        return classified
