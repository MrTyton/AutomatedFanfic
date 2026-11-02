"""Centralized configuration loader with caching, validation, and env overrides."""

import os
from pathlib import Path
import tomllib

from config.exceptions import ConfigError, ConfigValidationError
from config.schemas.app import AppConfig, toml_settings_context
import ff_logging


class ConfigManager:
    """Centralized configuration manager with caching and validation."""

    _cache: dict[str, AppConfig] = {}

    @classmethod
    def load_config(
        cls, config_path: str | Path, force_reload: bool = False
    ) -> AppConfig:
        """Loads and validates configuration from a TOML file with caching."""
        config_path = Path(config_path)
        cache_key = str(config_path.absolute())

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
            if "email" not in toml_data and not any(
                k.upper().startswith("FFDL_EMAIL") for k in os.environ
            ):
                raise ConfigValidationError(
                    "Missing required 'email' section in configuration.\n"
                    "Example configuration:\n"
                    "[email]\n"
                    "email = 'your-username'\n"
                    "password = 'your-password'\n"
                    "server = 'imap.gmail.com'"
                )
            if "calibre" not in toml_data and not any(
                k.upper().startswith("FFDL_CALIBRE") for k in os.environ
            ):
                raise ConfigValidationError(
                    "Missing required 'calibre' section in configuration.\n"
                    "Example configuration:\n"
                    "[calibre]\n"
                    "path = '/path/to/calibre/library'"
                )

            with toml_settings_context(toml_data):
                config = AppConfig()  # type: ignore[call-arg]
            cls._cache[cache_key] = config
            ff_logging.log(f"Configuration loaded successfully from {config_path}")
            return config

        except ConfigValidationError:
            raise
        except Exception as e:
            raise ConfigValidationError(f"Configuration validation failed: {e}")

    @classmethod
    def clear_cache(cls) -> None:
        """Clears the entire configuration cache."""
        cls._cache.clear()

    @classmethod
    def get_cached_config(cls, config_path: str | Path) -> AppConfig | None:
        """Retrieves a cached configuration without loading from disk."""
        cache_key = str(Path(config_path).absolute())
        return cls._cache.get(cache_key)


def get_config(config_path: str | Path) -> AppConfig | None:
    """Retrieves configuration from cache without loading from disk."""
    return ConfigManager.get_cached_config(config_path)


def load_config(config_path: str | Path) -> AppConfig:
    """Loads configuration from file with caching and validation."""
    return ConfigManager.load_config(config_path)
