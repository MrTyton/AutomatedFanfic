"""Delayed processing module for failed fanfiction downloads.

This module implements the AutomatedFanfic waiting queue system for handling
failed fanfiction downloads that need to be retried after exponential backoff
delays. It provides timer-based delayed requeuing functionality as part of the
Hail-Mary protocol for story processing failures.

Key Features:
    - Async-based delayed fanfiction reprocessing
    - Exponential backoff delay calculation based on retry counts
    - Asyncio task scheduling for delay management
    - Integration with site-specific processing queues
    - Graceful shutdown support via None sentinel pattern

Functions:
    schedule_delayed_retry: Async function for delayed queue insertion
    process_fanfic: Calculates delays and schedules fanfiction reprocessing
    wait_processor: Main waiting queue processor with continuous monitoring

Architecture:
    The module works with the broader asyncio architecture by receiving
    failed fanfiction entries in a waiting queue, calculating appropriate retry
    delays based on failure counts, and using asyncio.sleep() to schedule
    requeuing back to site-specific processing queues after the delay period.

Example:
    >>> # Used by TaskManager to start waiting queue processor
    >>> await wait_processor(site_queues, waiting_queue)
"""

import asyncio

import fanfic_info
import ff_logging
import retry_types


async def schedule_delayed_retry(
    delay_seconds: float, queue: asyncio.Queue, fanfic: fanfic_info.FanficInfo
) -> None:
    """Schedules a fanfiction entry for delayed retry after sleeping.

    Async function that waits for the specified delay and then inserts the
    fanfiction entry back into its appropriate site-specific processing queue.
    This is used for implementing exponential backoff retry logic.

    Args:
        delay_seconds (float): The delay in seconds before requeuing
        queue (asyncio.Queue): The asyncio queue to insert the fanfiction
                              entry into. Should be the site-specific queue that
                              corresponds to the fanfiction's source site.
        fanfic (fanfic_info.FanficInfo): The fanfiction metadata object to
                                        requeue for processing. Contains URL,
                                        site information, and retry state.

    Note:
        This is an async function that should be run as a task. Multiple
        such tasks can run concurrently for different fanfictions.

    Example:
        >>> # Usually called via asyncio.create_task
        >>> task = asyncio.create_task(
        ...     schedule_delayed_retry(300, queue, fanfic)
        ... )
    """
    await asyncio.sleep(delay_seconds)
    await queue.put(fanfic)


async def process_fanfic(
    fanfic: fanfic_info.FanficInfo,
    processor_queues: dict[str, asyncio.Queue],
) -> None:
    """Processes a failed fanfiction by scheduling delayed retry.

    Schedules delayed retry for fanfictions that have been routed to the waiting
    queue by url_worker after failure. Uses the retry decision that was already
    made and stored in the fanfic object to determine delay timing and logging.

    This function assumes the retry decision has already been made by url_worker
    and stored in fanfic.retry_decision. It focuses solely on implementing the
    delay timing and task scheduling.

    Args:
        fanfic (fanfic_info.FanficInfo): The fanfiction metadata object containing
                                        URL, site information, current retry state,
                                        and the pre-calculated retry decision.
        processor_queues (dict[str, asyncio.Queue]): Dictionary mapping site names to
                                                     their corresponding processing queues.

    Note:
        This function creates an async task that will execute independently.
        The task will call schedule_delayed_retry() when created.
        Multiple tasks can run concurrently for different fanfictions.
    """
    # Use the retry decision that was already calculated by url_worker
    decision = fanfic.retry_decision
    if decision is None:
        # Fallback in case decision wasn't set (shouldn't happen in normal flow)
        # Use a simple default retry with minimal delay
        ff_logging.log(
            f"No retry decision found for {fanfic.url}. Using default retry action.",
            "WARNING",
        )
        decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.RETRY,
            delay_minutes=5.0,  # Default 5 minute delay
            should_notify=False,
            notification_message="",
        )

    # Log the delay and schedule task
    if decision.action == retry_types.FailureAction.HAIL_MARY:
        ff_logging.log(
            f"Hail-Mary attempt: Waiting {decision.delay_minutes} minutes for {fanfic.url} "
            f"in queue {fanfic.site}",
            "WARNING",
        )
    elif decision.action == retry_types.FailureAction.RETRY:
        retry_count = fanfic.repeats or 0
        ff_logging.log(
            f"Waiting ~{decision.delay_minutes:.2f} minutes for {fanfic.url} in queue {fanfic.site} "
            f"(retry #{retry_count})",
            "WARNING",
        )
    else:
        # This shouldn't happen since url_worker already filtered out ABANDON cases
        ff_logging.log(
            f"Unexpected {decision.action.value} action in waiting queue for {fanfic.url}. "
            f"Abandoning processing.",
            "ERROR",
        )
        return

    # Convert delay to seconds and schedule task
    delay_seconds = decision.delay_minutes * 60
    target_queue = processor_queues[fanfic.site]
    
    # Create background task for delayed retry
    asyncio.create_task(
        schedule_delayed_retry(delay_seconds, target_queue, fanfic)
    )


async def wait_processor(
    processor_queues: dict[str, asyncio.Queue], waiting_queue: asyncio.Queue
) -> None:
    """Main waiting queue processor for handling delayed fanfiction retries.

    Continuously monitors the waiting queue for failed fanfiction entries that
    need delayed retry processing. Implements the waiting queue component of
    the retry protocol by receiving failed fanfictions and scheduling their
    delayed reprocessing via the pre-calculated retry decisions.

    This function runs as an async task and processes entries from the
    waiting queue in a continuous loop. Each failed fanfiction is processed
    via process_fanfic() which uses the pre-calculated retry decision to
    schedule delayed requeuing back to site-specific processing queues.

    Args:
        processor_queues (dict[str, asyncio.Queue]): Dictionary mapping fanfiction
                                                     site names (e.g., "archiveofourown.org")
                                                     to their corresponding asyncio
                                                     queues for site-specific processing.
        waiting_queue (asyncio.Queue): The shared asyncio queue containing
                                       failed fanfiction entries awaiting delayed retry.
                                       Supports None sentinel shutdown pattern.

    Note:
        This function runs indefinitely until a None entry (sentinel) is
        received in the waiting queue, which signals graceful shutdown. The
        5-second sleep prevents busy-waiting and reduces CPU usage.

    Shutdown:
        The function supports graceful shutdown via sentinel pattern. When
        TaskManager needs to stop this worker, it sends None to the queue,
        causing the function to break from its processing loop and return.

    Example:
        >>> # Typically called by TaskManager as async task
        >>> site_queues = {"archiveofourown.org": queue1, "fanfiction.net": queue2}
        >>> await wait_processor(site_queues, waiting_queue)
    """
    while True:
        try:
            # Wait for work with timeout to allow cancellation
            try:
                fanfic: fanfic_info.FanficInfo = await asyncio.wait_for(
                    waiting_queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                # No work available, continue to allow cancellation check
                continue

            # Check for sentinel shutdown signal (None entry)
            if fanfic is None:
                break

            # Schedule delayed retry processing for the failed fanfiction
            await process_fanfic(fanfic, processor_queues)

        except asyncio.CancelledError:
            # Task is being cancelled, exit gracefully
            ff_logging.log("Wait processor cancelled, shutting down")
            break
        except Exception as e:
            # Catch any unexpected errors to prevent task crash
            ff_logging.log_failure(f"Unexpected error in wait_processor: {e}")
            await asyncio.sleep(5)  # Brief pause before continuing
