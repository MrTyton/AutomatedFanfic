"""Process management and worker scaling configuration schema."""

import multiprocessing

import ff_logging
from pydantic import BaseModel, Field, field_validator


def get_cpu_count() -> int:
    """Safely determines the CPU count for default worker configuration."""
    try:
        return multiprocessing.cpu_count()
    except NotImplementedError, AttributeError:
        return 1


class ProcessConfig(BaseModel):
    """Configuration model for process management and monitoring."""

    # Graceful shutdown settings
    shutdown_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Timeout in seconds for graceful shutdown before force termination",
    )

    # Process health monitoring
    health_check_interval: float = Field(
        default=60.0,
        ge=0.1,
        le=600.0,
        description="Interval in seconds between process health checks",
    )

    # Process restart settings
    auto_restart: bool = Field(
        default=True, description="Automatically restart failed processes"
    )

    max_restart_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of restart attempts before giving up",
    )

    restart_delay: float = Field(
        default=5.0,
        ge=0.0,
        le=60.0,
        description="Delay in seconds before restarting a failed process",
    )

    # Process monitoring
    enable_monitoring: bool = Field(
        default=True,
        description="Enable process health monitoring and restart capabilities",
    )

    # Worker process settings
    max_workers: int = Field(
        default_factory=get_cpu_count,
        description="Maximum number of worker processes/threads",
    )
    worker_timeout: float | None = Field(
        default=None,
        ge=30.0,
        description="Timeout in seconds for individual worker operations",
    )

    # Signal handling
    signal_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Timeout in seconds to wait for signal handling completion",
    )

    @field_validator("max_workers")
    @classmethod
    def validate_max_workers(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_workers must be positive")
        if v == 1:
            ff_logging.log(
                "Warning: max_workers=1 may result in slow processing. "
                f"Consider using max_workers={get_cpu_count()} to utilize all CPU cores.",
                "WARNING",
            )
        return v
