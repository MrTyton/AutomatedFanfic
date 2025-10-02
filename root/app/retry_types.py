"""Types and utilities for retry logic and failure handling.

This module defines the core types and utilities used throughout the AutomatedFanfic
application for managing retry logic, failure handling, and the progression of
fanfiction processing attempts through various states.

The module centralizes retry-related type definitions to prevent typos, improve
type safety, and provide a single source of truth for retry behavior across
the multiprocessing architecture.
"""

import random

from enum import Enum
from typing import NamedTuple


class FailureAction(Enum):
    """Actions that can be taken when a fanfiction download fails.

    This enum defines the possible next steps after a download failure,
    providing type safety and preventing typos in string-based comparisons.
    The values progress from normal retry through escalated Hail-Mary
    protocol to final abandonment.

    Attributes:
        RETRY: Normal retry with exponential backoff delay
        HAIL_MARY: Final attempt after maximum normal retries with extended delay
        ABANDON: Permanent failure, no further processing attempts
    """

    RETRY = "retry"
    HAIL_MARY = "hail_mary"
    ABANDON = "abandon"


class RetryDecision(NamedTuple):
    """Result of retry logic decision making.

    This structured result contains both the action to take and any
    additional context needed for processing, such as delay timing
    or notification requirements.

    Attributes:
        action: The FailureAction to take next
        delay_minutes: Minutes to wait before next attempt (0 for immediate)
        should_notify: Whether to send notification for this action
        notification_message: Optional custom notification message
    """

    action: FailureAction
    delay_minutes: float = 0.0
    should_notify: bool = False
    notification_message: str = ""


def determine_retry_decision(
    current_repeats: int, retry_config, is_force_with_update_no_force: bool = False
) -> RetryDecision:
    """Determine the complete retry decision for a failed fanfiction download.

    This function encapsulates all retry logic decision making, determining
    the action to take, delay timing, and notification requirements based on
    current attempt count and configuration.

    Args:
        current_repeats: Number of times this story has failed so far
        retry_config: RetryConfig object with max_normal_retries, hail_mary settings
        is_force_with_update_no_force: Whether this is a force request with update_no_force config

    Returns:
        RetryDecision with action, delay, and notification information

    Examples:
        >>> config = RetryConfig(max_normal_retries=11, hail_mary_enabled=True)
        >>> determine_retry_decision(5, config)
        RetryDecision(action=FailureAction.RETRY, delay_minutes=5.0, ...)

        >>> determine_retry_decision(11, config)
        RetryDecision(action=FailureAction.HAIL_MARY, delay_minutes=720.0, ...)
    """

    if current_repeats < retry_config.max_normal_retries:
        # Normal retry with exponential backoff
        base_delay_minutes = min(
            current_repeats, 20
        )  # 1 min per retry, capped at 20 min
        jitter_multiplier = random.uniform(0.5, 1.5)  # ±50% jitter
        delay_minutes = base_delay_minutes * jitter_multiplier

        return RetryDecision(
            action=FailureAction.RETRY,
            delay_minutes=delay_minutes,
            should_notify=False,
            notification_message="",
        )

    elif (
        current_repeats == retry_config.max_normal_retries
        and retry_config.hail_mary_enabled
    ):
        # Hail-Mary protocol activation
        return RetryDecision(
            action=FailureAction.HAIL_MARY,
            delay_minutes=retry_config.hail_mary_wait_minutes,
            should_notify=True,
            notification_message="Fanfiction Download Failed, trying Hail-Mary in configured hours.",
        )

    else:
        # Abandonment - check for special notification case
        if is_force_with_update_no_force:
            notification_msg = (
                "Update permanently skipped because a force was requested "
                "but the update method is set to 'update_no_force'. The force "
                "request was ignored and a normal update was attempted instead."
            )
        else:
            notification_msg = ""

        return RetryDecision(
            action=FailureAction.ABANDON,
            delay_minutes=0.0,
            should_notify=is_force_with_update_no_force,
            notification_message=notification_msg,
        )


def determine_failure_action(
    current_repeats: int, max_normal_retries: int = 11, hail_mary_enabled: bool = True
) -> FailureAction:
    """Determine the next action for a failed fanfiction download.

    This function encapsulates the retry logic decision making, determining
    whether to retry normally, escalate to Hail-Mary protocol, or abandon
    the download based on current attempt count and configuration.

    Args:
        current_repeats: Number of times this story has failed so far
        max_normal_retries: Maximum normal retry attempts before Hail-Mary
        hail_mary_enabled: Whether Hail-Mary protocol is enabled

    Returns:
        FailureAction enum indicating next step to take

    Examples:
        >>> determine_failure_action(5, 11, True)
        FailureAction.RETRY

        >>> determine_failure_action(11, 11, True)
        FailureAction.HAIL_MARY

        >>> determine_failure_action(12, 11, True)
        FailureAction.ABANDON

        >>> determine_failure_action(11, 11, False)
        FailureAction.ABANDON
    """
    if current_repeats < max_normal_retries:
        return FailureAction.RETRY
    elif current_repeats == max_normal_retries and hail_mary_enabled:
        return FailureAction.HAIL_MARY
    else:
        return FailureAction.ABANDON
