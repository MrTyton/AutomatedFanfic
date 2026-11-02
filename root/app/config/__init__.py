"""Configuration package for AutomatedFanfic.

Provides Pydantic-based configuration schemas, environment variable overrides,
caching, validation, FanFicFare INI resolution, and cross-process shared store.
"""

from config.exceptions import ConfigError, ConfigValidationError
from config.ini_resolver import (
    build_fff_configuration,
    clear_ini_cache,
    get_packaged_defaults_ini_path,
    read_ini_file_cached,
    resolve_ini_path,
    resolve_state_personal_ini,
)
from config.loader import ConfigManager, get_config, load_config
from config.schemas import (
    AppConfig,
    AppriseConfig,
    CalibreConfig,
    EmailConfig,
    MetadataPreservationMode,
    ProcessConfig,
    PushbulletConfig,
    RetryConfig,
    UpdateMethod,
    WebConfig,
    get_cpu_count,
    toml_settings_context,
)
from config.store import FIELD_RELOAD_MAP, ConfigStore, ReloadBehavior
from config.toml_writer import TomlWriter

__all__ = [
    "ConfigError",
    "ConfigValidationError",
    "AppConfig",
    "EmailConfig",
    "CalibreConfig",
    "MetadataPreservationMode",
    "UpdateMethod",
    "PushbulletConfig",
    "AppriseConfig",
    "RetryConfig",
    "ProcessConfig",
    "get_cpu_count",
    "WebConfig",
    "ConfigManager",
    "load_config",
    "get_config",
    "ConfigStore",
    "ReloadBehavior",
    "FIELD_RELOAD_MAP",
    "TomlWriter",
    "resolve_ini_path",
    "resolve_state_personal_ini",
    "get_packaged_defaults_ini_path",
    "read_ini_file_cached",
    "clear_ini_cache",
    "build_fff_configuration",
    "toml_settings_context",
]
