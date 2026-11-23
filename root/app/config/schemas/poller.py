"""Library update poller configuration schema and validators."""

from pydantic import BaseModel, Field, field_validator, model_validator


class SitePollerConfig(BaseModel):
    """Adaptive polling and budget configuration for a single fanfiction site."""

    enabled: bool = Field(
        default=True,
        description="Whether adaptive polling is enabled for this site",
    )
    include_tags: list[str] = Field(
        default_factory=list,
        description=(
            "Calibre tags required for a story to be eligible for polling "
            "(empty list auto-detects from FanFicFare defaults.ini / personal.ini)"
        ),
    )
    exclude_tags: list[str] = Field(
        default_factory=list,
        description=(
            "Calibre tags that exclude a story from polling "
            "(empty list auto-detects from FanFicFare defaults.ini / personal.ini)"
        ),
    )
    calibre_search_override: str = Field(
        default="",
        description="Optional custom Calibre search query overriding include/exclude tags",
    )
    max_checks_per_day: int = Field(
        default=24,
        ge=1,
        description="Maximum number of update checks allowed per day for this site",
    )
    min_interval_minutes: float = Field(
        default=30.0,
        gt=0.0,
        description="Minimum cooldown interval in minutes between checks on this site",
    )
    hot_max_age_days: int = Field(
        default=14,
        ge=1,
        description="Maximum days since last update for a story to stay in the hot tier",
    )
    hot_interval_days: float = Field(
        default=1.5,
        gt=0.0,
        description="Polling interval in days for stories in the hot tier",
    )
    warm_max_age_days: int = Field(
        default=90,
        ge=1,
        description="Maximum days since last update for a story to stay in the warm tier",
    )
    warm_interval_days: float = Field(
        default=7.0,
        gt=0.0,
        description="Polling interval in days for stories in the warm tier",
    )
    cool_max_age_days: int = Field(
        default=365,
        ge=1,
        description="Maximum days since last update for a story to stay in the cool tier",
    )
    cool_interval_days: float = Field(
        default=21.0,
        gt=0.0,
        description="Polling interval in days for stories in the cool tier",
    )
    dormant_interval_days: float = Field(
        default=60.0,
        gt=0.0,
        description="Polling interval in days for stories older than cool_max_age_days",
    )
    jitter_ratio: float = Field(
        default=0.15,
        ge=0.0,
        le=0.5,
        description="Random jitter ratio applied to scheduled polling intervals (0.0-0.5)",
    )
    max_error_backoff_days: float = Field(
        default=30.0,
        gt=0.0,
        description="Maximum exponential backoff in days after consecutive check errors",
    )

    @model_validator(mode="after")
    def validate_tier_age_ordering(self) -> SitePollerConfig:
        """Ensure tier age thresholds strictly increase: hot < warm < cool."""
        if self.hot_max_age_days >= self.warm_max_age_days:
            raise ValueError(
                f"hot_max_age_days ({self.hot_max_age_days}) must be less than "
                f"warm_max_age_days ({self.warm_max_age_days})"
            )
        if self.warm_max_age_days >= self.cool_max_age_days:
            raise ValueError(
                f"warm_max_age_days ({self.warm_max_age_days}) must be less than "
                f"cool_max_age_days ({self.cool_max_age_days})"
            )
        return self


class LibraryPollerConfig(BaseModel):
    """Top-level configuration for the adaptive Calibre library update poller."""

    enabled: bool = Field(
        default=False,
        description="Enable the adaptive Calibre library update poller service",
    )
    library_sync_interval_hours: float = Field(
        default=6.0,
        gt=0.0,
        description="Interval in hours between full Calibre library sync scans",
    )
    tick_interval_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description="Scheduler tick interval in seconds for dispatching due checks",
    )
    sites: dict[str, SitePollerConfig] = Field(
        default_factory=dict,
        description="Per-site poller configurations keyed by normalized site identifier",
    )

    @field_validator("sites")
    @classmethod
    def normalize_site_keys(
        cls, v: dict[str, SitePollerConfig]
    ) -> dict[str, SitePollerConfig]:
        """Normalize site keys to lowercase stripped strings and reject empty/duplicate keys."""
        normalized: dict[str, SitePollerConfig] = {}
        for raw_key, site_cfg in v.items():
            key = raw_key.strip().lower()
            if not key:
                raise ValueError("Site key in library_poller.sites cannot be empty")
            if key in normalized:
                raise ValueError(
                    f"Duplicate site key '{key}' in library_poller.sites after normalization"
                )
            normalized[key] = site_cfg
        return normalized
