"""Custom configuration exceptions."""

from __future__ import annotations


class ConfigError(Exception):
    """Base exception for configuration-related errors."""

    pass


class ConfigValidationError(Exception):
    """Exception raised when configuration validation fails."""

    pass
