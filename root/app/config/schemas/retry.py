"""Retry and Hail-Mary configuration schema."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, PrivateAttr

if TYPE_CHECKING:
    from config.store import ConfigStore


class RetryConfig(BaseModel):
    """Configuration model for retry and Hail-Mary protocol settings."""

    hail_mary_enabled: bool = Field(
        default=True,
        description="Enable the Hail-Mary protocol for final retry attempts",
    )
    hail_mary_wait_hours: float = Field(
        default=12.0,
        ge=0.1,
        le=168.0,  # Maximum 1 week
        description="Hours to wait before attempting Hail-Mary retry",
    )
    max_normal_retries: int = Field(
        default=11,
        ge=1,
        le=50,
        description="Maximum number of normal retry attempts before Hail-Mary",
    )
    resume_uncompleted_on_startup: bool = Field(
        default=True,
        description="Whether to resume in-flight and waiting downloads from history database on startup",
    )

    _config_store: ConfigStore | None = PrivateAttr(default=None)

    def set_config_store(self, config_store: ConfigStore) -> None:
        """Attach a shared ConfigStore for hot-reloading retry settings."""
        self._config_store = config_store

    def update_from_config_store(self) -> bool:
        """Sync retry settings from the attached ConfigStore."""
        if self._config_store is None:
            return False
        changed = False
        mapping = {
            "max_normal_retries": "retry.max_normal_retries",
            "hail_mary_enabled": "retry.hail_mary_enabled",
            "hail_mary_wait_hours": "retry.hail_mary_wait_hours",
            "resume_uncompleted_on_startup": "retry.resume_uncompleted_on_startup",
        }
        for attr, key in mapping.items():
            val = self._config_store.get(key)
            if val is not None and val != getattr(self, attr, None):
                setattr(self, attr, val)
                changed = True
        return changed

    @property
    def hail_mary_wait_minutes(self) -> float:
        """Convert Hail-Mary wait time from hours to minutes for internal use."""
        return self.hail_mary_wait_hours * 60.0
