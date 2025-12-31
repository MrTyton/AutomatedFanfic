"""Base notification system for AutomatedFanfic application.

This module provides the abstract base class and retry mechanisms for implementing
notification systems in the AutomatedFanfic application. It defines the interface
that all notification providers must implement and provides robust retry logic
for handling transient notification failures.

Key Features:
    - Abstract base class ensuring consistent notification interface
    - Configuration loading and validation via ConfigManager integration
    - Retry decorator with exponential backoff for failure resilience
    - Enabled/disabled state management for notification providers
    - Error handling and logging for configuration failures

Classes:
    NotificationBase: Abstract base class for all notification implementations

Functions:
    retry_decorator: Decorator providing retry logic with exponential delays

Constants:
    kSleepTime: Base sleep time (10 seconds) for retry delays
    kMaxAttempts: Maximum retry attempts (3) before giving up

Architecture:
    Notification providers inherit from NotificationBase and implement
    send_notification(). The base class handles configuration loading,
    state management, and provides retry capabilities through decorators.

Example:
    >>> class MyNotifier(NotificationBase):
    ...     def send_notification(self, title, body, site):
    ...         # Implementation here
    ...         return True
    >>> notifier = MyNotifier("config.toml")
    >>> if notifier.enabled:
    ...     notifier.send_notification("Title", "Body", "site")
"""

import time
from typing import Callable, Any
from models.config_models import ConfigManager, ConfigError, ConfigValidationError
from utils import ff_logging

# Base sleep time in seconds for retry delays between notification attempts
kSleepTime = 10
# Maximum number of retry attempts before considering notification failed
kMaxAttempts = 3


class NotificationBase:
    """Abstract base class for all notification system implementations.

    Provides the foundation for notification providers in the AutomatedFanfic
    application. Handles configuration loading, validation, and state management
    while defining the interface that all concrete notification implementations
    must follow.

    The class loads and validates configuration from TOML files using ConfigManager,
    manages the enabled/disabled state of notification providers, and provides
    error handling for configuration failures. Derived classes must implement
    the abstract send_notification method and set self.enabled appropriately.

    Attributes:
        enabled (bool): Flag indicating whether the notification provider is
                       operational and ready to send notifications. Derived
                       classes must set this to True if properly configured.
        config (AppConfig | None): Loaded and validated configuration object
                                  from ConfigManager, or None if loading failed.

    Example:
        >>> class EmailNotifier(NotificationBase):
        ...     def __init__(self, toml_path):
        ...         super().__init__(toml_path)
        ...         if self.config and self.config.email.enabled:
        ...             self.enabled = True
        ...     def send_notification(self, title, body, site):
        ...         # Send email notification
        ...         return True
    """

    def __init__(self, toml_path: str, sleep_time: int = 10) -> None:
        """Initializes the notification base class with configuration loading.

        Loads and validates the TOML configuration file using ConfigManager,
        initializes the notification provider state, and handles configuration
        errors gracefully. Derived classes should call this constructor and
        then set self.enabled based on their specific configuration validation.

        Args:
            toml_path (str): Path to the TOML configuration file containing
                           notification settings and other application config.
            sleep_time (int, optional): Sleep time for retry delays. Currently
                                      unused but maintained for backward compatibility.
                                      Defaults to 10 seconds.

        Note:
            If configuration loading fails, self.config will be None and
            self.enabled will remain False. Derived classes should check
            self.config before attempting to use configuration values.

        Example:
            >>> notifier = MyNotifier("config.toml")
            >>> if notifier.config is None:
            ...     print("Configuration failed to load")
        """
        # Initialize as disabled until derived class validates configuration
        self.enabled = False

        # Load the configuration using ConfigManager with comprehensive error handling
        try:
            self.config = ConfigManager.load_config(toml_path)
        except (ConfigError, ConfigValidationError) as e:
            ff_logging.log_failure(f"Failed to load configuration: {e}")
            # Set to None to indicate configuration loading failed
            self.config = None

    def send_notification(self, title: str, body: str, site: str) -> bool:
        """Sends a notification with the specified title, body, and site context.

        Abstract method that must be implemented by all derived notification
        classes. This method defines the interface for sending notifications
        and should handle the actual notification delivery mechanism specific
        to each notification provider (email, push notifications, etc.).

        Args:
            title (str): The notification title/subject line. Should be concise
                        and descriptive of the notification purpose.
            body (str): The main notification content/message body containing
                       detailed information about the event or status.
            site (str): The fanfiction site context (e.g., "archiveofourown.org",
                       "fanfiction.net") for site-specific notification handling.

        Returns:
            bool: True if the notification was sent successfully, False if it
                 failed. This return value is used by retry decorators to
                 determine whether to retry the operation.

        Raises:
            NotImplementedError: Always raised since this is an abstract method
                               that must be implemented by derived classes.

        Example:
            >>> # In a derived class:
            >>> def send_notification(self, title, body, site):
            ...     try:
            ...         # Send notification via provider API
            ...         return True
            ...     except Exception:
            ...         return False
        """
        raise NotImplementedError(
            "send_notification method must be implemented in derived classes"
        )


def retry_decorator(func: Callable) -> Callable:
    """Decorator that retries notification functions with exponential backoff.

    Provides robust retry logic for notification functions that may fail due to
    transient network issues, API rate limits, or temporary service unavailability.
    Uses exponential backoff with increasing delays (10, 20, 30 seconds) between
    retry attempts to avoid overwhelming failing services.

    The decorator expects the wrapped function to return a boolean indicating
    success (True) or failure (False). If the function returns True, the retry
    loop stops immediately. If it returns False, the decorator waits for the
    calculated delay period before attempting the next retry.

    Args:
        func (Callable): The notification function to wrap with retry logic.
                        Must return bool where True indicates success and False
                        indicates failure requiring retry.

    Returns:
        Callable: A wrapper function that includes retry logic with exponential
                 backoff delays. The wrapper maintains the same signature as
                 the original function but adds retry behavior.

    Note:
        The retry delays are: 10 seconds (1st retry), 20 seconds (2nd retry),
        30 seconds (3rd retry). After 3 failed attempts, the function gives up
        and returns without further retries.

    Example:
        >>> @retry_decorator
        ... def send_push_notification(title, body, site):
        ...     # Attempt to send notification
        ...     return success_status  # True/False
        >>>
        >>> send_push_notification("Title", "Body", "site")  # Auto-retries on failure
    """

    def wrapper(*args: Any, **kwargs: Any) -> None:
        # Attempt notification with progressive retry delays
        for attempt in range(kMaxAttempts):
            # Try to send notification
            if func(*args, **kwargs):
                return  # Success - stop retrying
            elif attempt < kMaxAttempts - 1:
                # Calculate exponential backoff delay: 10s, 20s, 30s
                delay = kSleepTime * (attempt + 1)
                time.sleep(delay)

    return wrapper
