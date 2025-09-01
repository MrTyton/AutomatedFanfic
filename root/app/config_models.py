"""
Configuration models using Pydantic for type safety and validation.

This module defines all configuration structures used throughout the application,
providing centralized configuration management with validation and type hints.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import tomllib
import ff_logging


class ConfigError(Exception):
    """Base exception for configuration-related errors."""

    pass


class ConfigValidationError(Exception):
    """Exception raised when configuration validation fails."""

    pass


class EmailConfig(BaseModel):
    """Configuration for email monitoring."""

    email: str = Field(default="", description="Email address for monitoring")
    password: str = Field(default="", description="Email password or app password")
    server: str = Field(default="", description="IMAP server address")
    mailbox: str = Field(default="INBOX", description="Mailbox to monitor")
    sleep_time: int = Field(
        default=60, ge=1, description="Sleep time between checks in seconds"
    )
    ffnet_disable: bool = Field(
        default=True, description="Disable FanFiction.Net processing"
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        """Basic email validation - allow empty for development."""
        if v and ("@" not in v or "." not in v.split("@")[-1]):
            raise ValueError("Invalid email format")
        return v

    @field_validator("server")
    @classmethod
    def validate_server(cls, v):
        """Validate server address - allow empty for development."""
        return v.strip() if v else v

    def is_configured(self) -> bool:
        """Check if email is properly configured."""
        return bool(self.email and self.password and self.server)


class CalibreConfig(BaseModel):
    """Configuration for Calibre database access."""

    path: str = Field(default="", description="Path to Calibre library or server URL")
    username: Optional[str] = Field(default=None, description="Calibre username")
    password: Optional[str] = Field(default=None, description="Calibre password")
    default_ini: Optional[str] = Field(
        default=None, description="Path to defaults.ini file"
    )
    personal_ini: Optional[str] = Field(
        default=None, description="Path to personal.ini file"
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v):
        """Validate Calibre path - can be local path or URL."""
        if not v or not v.strip():
            # Allow empty for development/testing
            return v

        path_str = v.strip()

        # Check if it's a URL (contains :// or starts with http)
        if "://" in path_str or path_str.startswith("http"):
            return path_str

        # Check if it's a local path
        path_obj = Path(path_str)
        if not path_obj.exists():
            ff_logging.log_debug(
                f"Warning: Calibre path {path_str} does not exist locally"
            )

        return path_str

    @model_validator(mode="after")
    def validate_authentication(self):
        """Validate that if username is provided, password should also be provided."""
        if self.username and not self.password:
            ff_logging.log_debug("Warning: Username provided without password")
        elif self.password and not self.username:
            ff_logging.log_debug("Warning: Password provided without username")

        return self

    def is_configured(self) -> bool:
        """Check if Calibre is properly configured."""
        return bool(self.path and self.path.strip())


class PushbulletConfig(BaseModel):
    """Configuration for Pushbullet notifications."""

    enabled: bool = Field(default=False, description="Enable Pushbullet notifications")
    token: Optional[str] = Field(default=None, description="Pushbullet API token")
    device: Optional[str] = Field(default=None, description="Target device name")

    @model_validator(mode="after")
    def validate_pushbullet(self):
        """Validate Pushbullet configuration."""
        if self.enabled and not self.token:
            raise ValueError("Pushbullet token is required when enabled=True")

        return self


class AppriseConfig(BaseModel):
    """Configuration for Apprise notifications."""

    urls: List[str] = Field(
        default_factory=list, description="List of Apprise notification URLs"
    )

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, v):
        """Validate Apprise URLs."""
        if not isinstance(v, list):
            raise ValueError("Apprise URLs must be a list")

        # Filter out empty strings
        return [url.strip() for url in v if url and url.strip()]


class AppConfig(BaseSettings):
    """Main application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # Configuration sections
    email: EmailConfig
    calibre: CalibreConfig
    pushbullet: PushbulletConfig = Field(default_factory=PushbulletConfig)
    apprise: AppriseConfig = Field(default_factory=AppriseConfig)

    # Application settings
    version: str = Field(default="1.3.23", description="Application version")
    max_workers: Optional[int] = Field(
        default=None, description="Maximum number of worker processes"
    )

    @model_validator(mode="after")
    def validate_worker_count(self):
        """Validate and set default worker count."""
        if self.max_workers is None:
            import multiprocessing

            self.max_workers = multiprocessing.cpu_count()
        elif self.max_workers <= 0:
            raise ValueError("max_workers must be positive")

        return self


class ConfigManager:
    """Centralized configuration manager with caching."""

    _cache: Dict[str, AppConfig] = {}

    @classmethod
    def load_config(
        cls, config_path: Union[str, Path], force_reload: bool = False
    ) -> AppConfig:
        """
        Load configuration from TOML file with caching.

        Args:
            config_path: Path to the TOML configuration file
            force_reload: Force reload even if cached

        Returns:
            AppConfig: Validated configuration object

        Raises:
            ConfigError: If config file doesn't exist or parsing fails
            ConfigValidationError: If config validation fails
        """
        config_path = Path(config_path)
        cache_key = str(config_path.absolute())

        # Return cached config unless force reload is requested
        if not force_reload and cache_key in cls._cache:
            return cls._cache[cache_key]

        if not config_path.exists():
            raise ConfigError(f"Configuration file not found: {config_path}")

        try:
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)

        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Error parsing configuration file {config_path}: {e}")
        except Exception as e:
            raise ConfigError(f"Error parsing configuration file {config_path}: {e}")

        try:
            # Validate required sections
            if "email" not in toml_data:
                raise ConfigValidationError(
                    "Missing required 'email' section in configuration"
                )
            if "calibre" not in toml_data:
                raise ConfigValidationError(
                    "Missing required 'calibre' section in configuration"
                )

            # Create configuration with validation
            config = AppConfig(**toml_data)

            # Cache the configuration
            cls._cache[cache_key] = config

            ff_logging.log(f"Configuration loaded successfully from {config_path}")
            return config

        except ConfigValidationError:
            raise  # Re-raise validation errors as-is
        except Exception as e:
            raise ConfigValidationError(f"Configuration validation failed: {e}")

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the configuration cache."""
        cls._cache.clear()

    @classmethod
    def get_cached_config(cls, config_path: Union[str, Path]) -> Optional[AppConfig]:
        """Get cached configuration without loading."""
        cache_key = str(Path(config_path).absolute())
        return cls._cache.get(cache_key)


# Helper functions for global configuration access
def get_config(config_path: Union[str, Path]) -> Optional[AppConfig]:
    """Get configuration from cache or load if not cached."""
    return ConfigManager.get_cached_config(config_path)


def load_config(config_path: Union[str, Path]) -> AppConfig:
    """Load configuration from file."""
    return ConfigManager.load_config(config_path)
