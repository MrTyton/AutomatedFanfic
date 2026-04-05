"""Shared configuration store for cross-process hot-reload.

Wraps a multiprocessing Manager dict to share hot-reloadable config values
between all processes. Services read from this store each iteration instead
of their local config copies.
"""

from enum import Enum
from typing import Any


class ReloadBehavior(str, Enum):
    """How the system reacts when a config field changes."""

    HOT = "hot"  # Updated immediately via shared dict
    SERVICE_RESTART = "service_restart"  # Requires supervisor/worker restart
    APP_RESTART = "app_restart"  # Requires full container restart


# Exhaustive map of dotted field keys → reload behaviour
FIELD_RELOAD_MAP: dict[str, ReloadBehavior] = {
    # ── Hot-reloadable ──────────────────────────────────────────
    "email.sleep_time": ReloadBehavior.HOT,
    "email.disabled_sites": ReloadBehavior.HOT,
    "calibre.update_method": ReloadBehavior.HOT,
    "calibre.metadata_preservation_mode": ReloadBehavior.HOT,
    "retry.max_normal_retries": ReloadBehavior.HOT,
    "retry.hail_mary_enabled": ReloadBehavior.HOT,
    "retry.hail_mary_wait_hours": ReloadBehavior.HOT,
    # ── Service restart ─────────────────────────────────────────
    "email.email": ReloadBehavior.SERVICE_RESTART,
    "email.password": ReloadBehavior.SERVICE_RESTART,
    "email.server": ReloadBehavior.SERVICE_RESTART,
    "email.mailbox": ReloadBehavior.SERVICE_RESTART,
    "calibre.path": ReloadBehavior.SERVICE_RESTART,
    "calibre.username": ReloadBehavior.SERVICE_RESTART,
    "calibre.password": ReloadBehavior.SERVICE_RESTART,
    "calibre.default_ini": ReloadBehavior.SERVICE_RESTART,
    "calibre.personal_ini": ReloadBehavior.SERVICE_RESTART,
    "pushbullet.enabled": ReloadBehavior.SERVICE_RESTART,
    "pushbullet.api_key": ReloadBehavior.SERVICE_RESTART,
    "pushbullet.device": ReloadBehavior.SERVICE_RESTART,
    "apprise.urls": ReloadBehavior.SERVICE_RESTART,
    # ── App restart ─────────────────────────────────────────────
    "max_workers": ReloadBehavior.APP_RESTART,
    "web.enabled": ReloadBehavior.APP_RESTART,
    "web.host": ReloadBehavior.APP_RESTART,
    "web.port": ReloadBehavior.APP_RESTART,
    "process.shutdown_timeout": ReloadBehavior.APP_RESTART,
    "process.health_check_interval": ReloadBehavior.APP_RESTART,
    "process.max_restart_attempts": ReloadBehavior.APP_RESTART,
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
        self._store["email.sleep_time"] = config.email.sleep_time
        self._store["email.disabled_sites"] = list(config.email.disabled_sites)
        self._store["calibre.update_method"] = config.calibre.update_method
        self._store["calibre.metadata_preservation_mode"] = (
            config.calibre.metadata_preservation_mode.value
            if hasattr(config.calibre.metadata_preservation_mode, "value")
            else config.calibre.metadata_preservation_mode
        )
        self._store["retry.max_normal_retries"] = config.retry.max_normal_retries
        self._store["retry.hail_mary_enabled"] = config.retry.hail_mary_enabled
        self._store["retry.hail_mary_wait_hours"] = config.retry.hail_mary_wait_hours

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
