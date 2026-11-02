"""Custom configuration exceptions."""


class ConfigError(Exception):
    """Base exception for configuration-related errors."""


class ConfigValidationError(Exception):
    """Exception raised when configuration validation fails."""
