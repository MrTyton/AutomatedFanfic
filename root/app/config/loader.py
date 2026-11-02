"""Centralized configuration loader with caching, validation, and env overrides."""

import os
from pathlib import Path
import re
import tomllib
from typing import TYPE_CHECKING

import ff_logging
from config.exceptions import ConfigError, ConfigValidationError
from config.schemas.app import AppConfig

if TYPE_CHECKING:
    pass


class ConfigManager:
    """Centralized configuration manager with caching and validation."""

    _cache: dict[str, AppConfig] = {}

    @staticmethod
    def _coerce_env_value(section: str | None, field: str | None, value: str) -> object:
        """Best-effort coercion for env override values."""
        raw = value.strip()
        lower = raw.lower()

        if lower in {"true", "false"}:
            return lower == "true"

        if section in {"email", "apprise"} and field in {"disabled_sites", "urls"}:
            return [item.strip() for item in raw.split(",") if item.strip()]

        if re.match(r"^-?\d+$", raw):
            return int(raw)
        if re.match(r"^-?\d+\.\d+$", raw):
            return float(raw)

        return raw

    @staticmethod
    def _set_nested_value(data: dict, path_parts: list[str], value: object) -> None:
        """Set a nested dictionary value, creating intermediate dictionaries."""
        if not path_parts:
            return

        current = data
        for part in path_parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[path_parts[-1]] = value

    @classmethod
    def _apply_environment_overrides(cls, toml_data: dict) -> dict:
        """Apply FFDL_* environment variables as overrides on top of TOML data."""
        merged = dict(toml_data)

        for key, env_value in os.environ.items():
            if not key.startswith("FFDL_"):
                continue

            suffix = key[len("FFDL_") :]
            if not suffix:
                continue

            if "__" in suffix:
                parts = [p.lower() for p in suffix.split("__") if p]
            elif "_" in suffix:
                section, field = suffix.split("_", 1)
                parts = [section.lower(), field.lower()]
            else:
                parts = [suffix.lower()]

            section = parts[0] if len(parts) > 1 else None
            field = parts[1] if len(parts) > 1 else parts[0]
            coerced = cls._coerce_env_value(section, field, env_value)
            cls._set_nested_value(merged, parts, coerced)

        return merged

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

            toml_data = cls._apply_environment_overrides(toml_data)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Error parsing configuration file {config_path}: {e}")
        except Exception as e:
            raise ConfigError(f"Error parsing configuration file {config_path}: {e}")

        try:
            if "email" not in toml_data:
                raise ConfigValidationError(
                    "Missing required 'email' section in configuration.\n"
                    "Example configuration:\n"
                    "[email]\n"
                    "email = 'your-username'\n"
                    "password = 'your-password'\n"
                    "server = 'imap.gmail.com'"
                )
            if "calibre" not in toml_data:
                raise ConfigValidationError(
                    "Missing required 'calibre' section in configuration.\n"
                    "Example configuration:\n"
                    "[calibre]\n"
                    "path = '/path/to/calibre/library'"
                )

            config = AppConfig(**toml_data)
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
