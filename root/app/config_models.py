"""Configuration models using Pydantic for type safety and validation.

This module defines all configuration structures used throughout the AutomatedFanfic
application, providing centralized configuration management with comprehensive
validation and type hints. It includes models for email, Calibre, notification,
and process management configurations with TOML file integration.

Key Features:
    - Pydantic-based configuration models with automatic validation
    - TOML file parsing and loading with error handling
    - Email configuration with IMAP server support
    - Calibre library configuration for local and server-based libraries
    - Notification provider configuration (Pushbullet, Apprise)
    - Process management configuration with health monitoring
    - Comprehensive field validation and constraint enforcement

Classes:
    EmailConfig: Email monitoring and IMAP server configuration
    CalibreConfig: Calibre library path and authentication settings
    PushbulletConfig: Pushbullet notification service configuration
    AppriseConfig: Apprise notification framework configuration
    ProcessConfig: Multiprocessing and health monitoring configuration
    AppConfig: Root configuration aggregating all subsystem configs
    ConfigManager: Configuration loading and management utilities

Exception Classes:
    ConfigError: Base configuration error class
    ConfigValidationError: Configuration validation error class

The configuration system supports both local development and production deployment
scenarios with comprehensive validation to prevent runtime configuration errors.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import tomllib
import ff_logging


class ConfigError(Exception):
    """Base exception for configuration-related errors.

    This exception serves as the base class for all configuration-related errors
    in the application. It is raised when configuration files cannot be loaded,
    parsed, or when there are fundamental issues with configuration access.

    Examples of scenarios that raise ConfigError:
        - Configuration file not found
        - TOML parsing errors
        - File access permission issues
        - Invalid file format
    """

    pass


class ConfigValidationError(Exception):
    """Exception raised when configuration validation fails.

    This exception is raised when configuration data fails Pydantic validation
    or when custom validation rules are violated. It indicates that while the
    configuration file could be parsed, the values do not meet the application's
    requirements or constraints.

    Examples of scenarios that raise ConfigValidationError:
        - Missing required configuration sections
        - Invalid data types for configuration values
        - Values outside acceptable ranges
        - Invalid combinations of configuration options
    """

    pass


class EmailConfig(BaseModel):
    """Configuration model for email monitoring and authentication.

    This class defines the configuration structure for email-based fanfiction URL
    monitoring. It handles IMAP server connection settings, authentication
    credentials, and monitoring behavior. The model includes validation to ensure
    proper email configuration and prevent common configuration errors.

    Attributes:
        email (str): Email authentication field (username only or full email address).
        password (str): Password or app-specific password for email authentication.
        server (str): IMAP server address (e.g., 'imap.gmail.com').
        mailbox (str): Mailbox name to monitor for new emails (default: 'INBOX').
        sleep_time (int): Interval in seconds between email checks (minimum: 1).
        ffnet_disable (bool): Whether to disable FanFiction.Net processing.

    Note:
        Different email providers have different authentication requirements.
        Some require just the username, while others require the full email address.
    """

    email: str = Field(
        default="", description="Email authentication (username or full email address)"
    )
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
        """Validates and normalizes the email field.

        Different email providers have different authentication requirements:
        some require just the username portion, while others require the full
        email address including the @domain. Users should configure this field
        according to their specific email provider's requirements.

        Args:
            v (str): The email value to validate.

        Returns:
            str: The validated and trimmed email value.
        """
        return v.strip() if v else v

    @field_validator("server")
    @classmethod
    def validate_server(cls, v):
        """Validates and normalizes the server address.

        Trims whitespace from the server address to prevent connection issues
        caused by inadvertent spacing. Allows empty values for development
        or testing scenarios.

        Args:
            v (str): The server address to validate.

        Returns:
            str: The validated and trimmed server address.
        """
        return v.strip() if v else v

    def is_configured(self) -> bool:
        """Checks if email configuration is complete and ready for use.

        Validates that all essential email configuration fields are provided
        and non-empty, indicating that the email monitoring functionality
        can be properly initialized.

        Returns:
            bool: True if email, password, and server are all configured,
                False otherwise.
        """
        return bool(self.email and self.password and self.server)


class CalibreConfig(BaseModel):
    """Configuration model for Calibre e-book library integration.

    This class defines the configuration structure for connecting to and interacting
    with Calibre e-book libraries. It supports both local library directories and
    remote Calibre Content Server instances, with optional authentication and
    FanFicFare integration settings.

    Attributes:
        path (str): Path to local Calibre library or URL to Calibre Content Server.
        username (Optional[str]): Username for Calibre server authentication.
        password (Optional[str]): Password for Calibre server authentication.
        default_ini (Optional[str]): Path to FanFicFare defaults.ini configuration.
        personal_ini (Optional[str]): Path to FanFicFare personal.ini configuration.
        update_method (Literal): Method for updating stories - 'update', 'update_always',
            'force', or 'update_no_force'.

    Note:
        The path field accepts either local filesystem paths or HTTP(S) URLs for
        remote Calibre Content Server instances. Authentication is only required
        for protected server instances.
    """

    path: str = Field(default="", description="Path to Calibre library or server URL")
    username: Optional[str] = Field(default=None, description="Calibre username")
    password: Optional[str] = Field(default=None, description="Calibre password")
    default_ini: Optional[str] = Field(
        default=None, description="Path to defaults.ini file"
    )
    personal_ini: Optional[str] = Field(
        default=None, description="Path to personal.ini file"
    )
    update_method: Literal["update", "update_always", "force", "update_no_force"] = (
        Field(
            default="update",
            description="Fanficfare update method: 'update', 'update_always', 'force', or 'update_no_force'",
        )
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v):
        """Validates Calibre library path or server URL.

        Accepts both local filesystem paths and HTTP(S) URLs for Calibre Content
        Server instances. For local paths, logs a warning if the path doesn't exist
        but doesn't raise an error to allow for flexible deployment scenarios.

        Args:
            v (str): The path or URL to validate.

        Returns:
            str: The validated and trimmed path or URL.

        Note:
            Empty paths are allowed for development/testing scenarios.
        """
        if not v or not v.strip():
            # Allow empty for development/testing
            return v

        path_str = v.strip()

        # Check if it's a URL (contains :// or starts with http)
        if "://" in path_str or path_str.startswith("http"):
            return path_str

        # Check if it's a local path and log warning if it doesn't exist
        path_obj = Path(path_str)
        if not path_obj.exists():
            ff_logging.log_debug(
                f"Warning: Calibre path {path_str} does not exist locally"
            )

        return path_str

    @model_validator(mode="after")
    def validate_authentication(self):
        """Validates authentication credential consistency.

        Ensures that if authentication credentials are provided, both username
        and password are present. Logs warnings for incomplete authentication
        configurations that might cause connection issues.

        Returns:
            CalibreConfig: The validated configuration instance.

        Note:
            This validation logs warnings rather than raising errors to allow
            for flexible authentication scenarios during development.
        """
        if self.username and not self.password:
            ff_logging.log_debug("Warning: Username provided without password")
        elif self.password and not self.username:
            ff_logging.log_debug("Warning: Password provided without username")

        return self

    def is_configured(self) -> bool:
        """Checks if Calibre configuration is complete and ready for use.

        Validates that the essential path field is provided and non-empty,
        indicating that the Calibre integration functionality can be properly
        initialized.

        Returns:
            bool: True if path is configured and non-empty, False otherwise.
        """
        return bool(self.path and self.path.strip())


class PushbulletConfig(BaseModel):
    """Configuration model for Pushbullet notification service.

    This class defines the configuration structure for Pushbullet notifications,
    including API authentication and optional device targeting. It ensures that
    when Pushbullet notifications are enabled, the required API key is provided.

    Attributes:
        enabled (bool): Whether Pushbullet notifications are enabled.
        api_key (Optional[str]): Pushbullet API key for authentication.
        device (Optional[str]): Optional target device name for notifications.

    Note:
        When enabled=True, the api_key field becomes required. The device field
        is optional and notifications will be sent to all devices if not specified.
    """

    enabled: bool = Field(default=False, description="Enable Pushbullet notifications")
    api_key: Optional[str] = Field(default=None, description="Pushbullet API key")
    device: Optional[str] = Field(default=None, description="Target device name")

    @model_validator(mode="after")
    def validate_pushbullet(self):
        """Validates Pushbullet configuration consistency.

        Ensures that when Pushbullet notifications are enabled, the required
        API key is provided. This prevents runtime errors when attempting to
        send notifications without proper authentication.

        Returns:
            PushbulletConfig: The validated configuration instance.

        Raises:
            ValueError: If enabled=True but api_key is not provided.
        """
        if self.enabled and not self.api_key:
            raise ValueError("Pushbullet api_key is required when enabled=True")

        return self


class AppriseConfig(BaseModel):
    """Configuration model for Apprise notification services.

    This class defines the configuration structure for Apprise-based notifications,
    which supports a wide variety of notification services through URL-based
    configuration. It validates and normalizes the list of service URLs.

    Attributes:
        urls (List[str]): List of Apprise service URLs for notification targets.

    Note:
        Apprise URLs follow specific formats for different services. See the
        Apprise documentation for supported services and URL formats. Empty
        strings are automatically filtered out during validation.
    """

    urls: List[str] = Field(
        default_factory=list, description="List of Apprise notification URLs"
    )

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, v):
        """Validates and normalizes the list of Apprise service URLs.

        Ensures that the URLs field is a list and filters out empty or
        whitespace-only entries to prevent configuration issues with
        invalid URL entries.

        Args:
            v: The URLs value to validate.

        Returns:
            List[str]: The validated list of non-empty, trimmed URLs.

        Raises:
            ValueError: If the urls field is not a list.
        """
        if not isinstance(v, list):
            raise ValueError("Apprise URLs must be a list")

        # Filter out empty strings and trim whitespace
        return [url.strip() for url in v if url and url.strip()]


class ProcessConfig(BaseModel):
    """Configuration model for process management and monitoring.

    This class defines comprehensive settings for managing worker processes,
    including graceful shutdown behavior, health monitoring, automatic restart
    capabilities, and signal handling. It provides fine-grained control over
    process lifecycle management to ensure reliable operation.

    Attributes:
        shutdown_timeout (float): Maximum time to wait for graceful shutdown.
        health_check_interval (float): Interval between process health checks.
        auto_restart (bool): Whether to automatically restart failed processes.
        max_restart_attempts (int): Maximum restart attempts before giving up.
        restart_delay (float): Delay before restarting a failed process.
        enable_monitoring (bool): Whether to enable process health monitoring.
        worker_timeout (Optional[float]): Timeout for individual worker operations.
        signal_timeout (float): Timeout for signal handling completion.

    Note:
        All timing values are in seconds and include validation ranges to prevent
        invalid configurations that could cause system instability.
    """

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
    worker_timeout: Optional[float] = Field(
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


class AppConfig(BaseSettings):
    """Main application configuration container and validator.

    This class serves as the root configuration model that combines all
    configuration sections into a unified structure. It provides environment
    variable support and validates cross-section dependencies to ensure
    the application is properly configured.

    Attributes:
        email (EmailConfig): Email monitoring configuration section.
        calibre (CalibreConfig): Calibre library integration configuration.
        pushbullet (PushbulletConfig): Pushbullet notification configuration.
        apprise (AppriseConfig): Apprise notification services configuration.
        process (ProcessConfig): Process management and monitoring configuration.
        version (str): Application version string.
        max_workers (Optional[int]): Maximum number of worker processes.

    Note:
        The configuration supports environment variable overrides following
        Pydantic's naming conventions. Worker count defaults to CPU count
        if not explicitly specified.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # Configuration sections
    email: EmailConfig
    calibre: CalibreConfig
    pushbullet: PushbulletConfig = Field(default_factory=PushbulletConfig)
    apprise: AppriseConfig = Field(default_factory=AppriseConfig)
    process: ProcessConfig = Field(default_factory=ProcessConfig)

    # Application settings
    version: str = Field(default="1.3.23", description="Application version")
    max_workers: Optional[int] = Field(
        default=None, description="Maximum number of worker processes"
    )

    @model_validator(mode="after")
    def validate_worker_count(self):
        """Validates and sets default worker process count.

        Automatically sets the maximum worker count to match the system's
        CPU count if not explicitly configured. Ensures that the worker
        count is positive to prevent invalid process configurations.

        Returns:
            AppConfig: The validated configuration instance with worker count set.

        Raises:
            ValueError: If max_workers is explicitly set to zero or negative.

        Note:
            The default behavior uses multiprocessing.cpu_count() to optimize
            for the target system's capabilities.
        """
        if self.max_workers is None:
            # Default to CPU count for optimal performance
            import multiprocessing

            self.max_workers = multiprocessing.cpu_count()
        elif self.max_workers <= 0:
            raise ValueError("max_workers must be positive")

        return self


class ConfigManager:
    """Centralized configuration manager with caching and validation.

    This class provides a centralized interface for loading, caching, and managing
    application configuration from TOML files. It implements caching to avoid
    repeated file parsing and provides comprehensive error handling for
    configuration loading and validation scenarios.

    Class Attributes:
        _cache (Dict[str, AppConfig]): Internal cache storing loaded configurations
            keyed by absolute file path.

    Note:
        The cache uses absolute file paths as keys to ensure consistency across
        different working directories and relative path references.
    """

    _cache: Dict[str, AppConfig] = {}

    @classmethod
    def load_config(
        cls, config_path: Union[str, Path], force_reload: bool = False
    ) -> AppConfig:
        """Loads and validates configuration from a TOML file with caching.

        Reads configuration from the specified TOML file, validates it against
        the application's configuration schema, and caches the result for
        future use. Provides comprehensive error handling for file access,
        parsing, and validation issues.

        Args:
            config_path (Union[str, Path]): Path to the TOML configuration file
                to load. Can be a string or Path object.
            force_reload (bool, optional): If True, bypasses the cache and
                reloads the configuration from disk. Defaults to False.

        Returns:
            AppConfig: A validated configuration object containing all
                application settings and their validated values.

        Raises:
            ConfigError: If the configuration file doesn't exist, cannot be
                read, or has TOML parsing errors.
            ConfigValidationError: If the configuration file is valid TOML
                but fails Pydantic validation or missing required sections.

        Note:
            Cached configurations are keyed by absolute path, so the same
            configuration file referenced through different relative paths
            will share the same cache entry.
        """
        config_path = Path(config_path)
        cache_key = str(config_path.absolute())

        # Return cached config unless force reload is requested
        if not force_reload and cache_key in cls._cache:
            return cls._cache[cache_key]

        # Verify file exists before attempting to load
        if not config_path.exists():
            raise ConfigError(f"Configuration file not found: {config_path}")

        try:
            # Load and parse TOML content
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)

        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Error parsing configuration file {config_path}: {e}")
        except Exception as e:
            raise ConfigError(f"Error parsing configuration file {config_path}: {e}")

        try:
            # Validate required sections exist
            if "email" not in toml_data:
                raise ConfigValidationError(
                    "Missing required 'email' section in configuration"
                )
            if "calibre" not in toml_data:
                raise ConfigValidationError(
                    "Missing required 'calibre' section in configuration"
                )

            # Create and validate configuration object
            config = AppConfig(**toml_data)

            # Cache the validated configuration
            cls._cache[cache_key] = config

            ff_logging.log(f"Configuration loaded successfully from {config_path}")
            return config

        except ConfigValidationError:
            # Re-raise validation errors as-is for specific handling
            raise
        except Exception as e:
            # Wrap other exceptions in ConfigValidationError
            raise ConfigValidationError(f"Configuration validation failed: {e}")

    @classmethod
    def clear_cache(cls) -> None:
        """Clears the entire configuration cache.

        Removes all cached configuration objects, forcing subsequent loads
        to read from disk. Useful for testing scenarios or when configuration
        files have been modified externally.
        """
        cls._cache.clear()

    @classmethod
    def get_cached_config(cls, config_path: Union[str, Path]) -> Optional[AppConfig]:
        """Retrieves a cached configuration without loading from disk.

        Looks up a previously loaded configuration in the cache without
        attempting to load or validate the file. Useful for checking if
        a configuration is already loaded.

        Args:
            config_path (Union[str, Path]): Path to the configuration file
                to look up in the cache.

        Returns:
            Optional[AppConfig]: The cached configuration object if found,
                None if the configuration is not in the cache.

        Note:
            The lookup is based on absolute path, so different relative
            paths to the same file will find the same cache entry.
        """
        cache_key = str(Path(config_path).absolute())
        return cls._cache.get(cache_key)


# Helper functions for global configuration access
def get_config(config_path: Union[str, Path]) -> Optional[AppConfig]:
    """Retrieves configuration from cache without loading from disk.

    This convenience function provides a simple interface to check if a
    configuration is already loaded and cached. It does not attempt to
    load the configuration if it's not found in the cache.

    Args:
        config_path (Union[str, Path]): Path to the configuration file
            to retrieve from the cache.

    Returns:
        Optional[AppConfig]: The cached configuration object if available,
            None if not found in cache.

    Note:
        This function is a simple wrapper around ConfigManager.get_cached_config()
        for backward compatibility and convenience.
    """
    return ConfigManager.get_cached_config(config_path)


def load_config(config_path: Union[str, Path]) -> AppConfig:
    """Loads configuration from file with caching and validation.

    This convenience function provides a simple interface to load configuration
    from a TOML file. It uses the ConfigManager's caching functionality to
    avoid repeated parsing of the same configuration file.

    Args:
        config_path (Union[str, Path]): Path to the TOML configuration file
            to load and validate.

    Returns:
        AppConfig: A validated configuration object containing all
            application settings.

    Raises:
        ConfigError: If the configuration file doesn't exist, cannot be
            read, or has TOML parsing errors.
        ConfigValidationError: If the configuration fails validation.

    Note:
        This function is a simple wrapper around ConfigManager.load_config()
        for backward compatibility and convenience.
    """
    return ConfigManager.load_config(config_path)
