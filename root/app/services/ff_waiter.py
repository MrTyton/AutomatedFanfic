"""Delayed processing module for failed fanfiction downloads.

This module implements the AutomatedFanfic waiting queue system for handling
failed fanfiction downloads that need to be retried after exponential backoff
delays. It provides timer-based delayed requeuing functionality as part of the
Hail-Mary protocol for story processing failures.

Key Features:
    - Timer-based delayed fanfiction reprocessing
    - Exponential backoff delay calculation based on retry counts
    - Threading-based delay management without blocking main processes
    - Integration with site-specific processing queues
    - Graceful shutdown support via poison pill pattern

Functions:
    insert_after_time: Timer callback for delayed queue insertion
    process_fanfic: Calculates delays and schedules fanfiction reprocessing
    wait_processor: Main waiting queue processor with continuous monitoring

Architecture:
    The module works with the broader multiprocessing architecture by receiving
    failed fanfiction entries in a waiting queue, calculating appropriate retry
    delays based on failure counts, and using threading.Timer to schedule
    requeuing back to site-specific processing queues after the delay period.

Example:
    >>> # Used by ProcessManager to start waiting queue processor
    >>> wait_processor(site_queues, waiting_queue)
"""

import multiprocessing as mp
import threading
from time import sleep

from models import fanfic_info
from utils import ff_logging
from models import retry_types


def insert_after_time(queue: mp.Queue, fanfic: fanfic_info.FanficInfo) -> None:
    """Inserts a fanfiction entry into a processing queue after timer delay.

    Timer callback function used by threading.Timer to requeue a fanfiction
    entry back into its appropriate site-specific processing queue after a
    calculated delay period. This function is called asynchronously when
    the retry timer expires.

    Args:
        queue (mp.Queue): The multiprocessing queue to insert the fanfiction
                         entry into. Should be the site-specific queue that
                         corresponds to the fanfiction's source site.
        fanfic (fanfic_info.FanficInfo): The fanfiction metadata object to
                                        requeue for processing. Contains URL,
                                        site information, and retry state.

    Note:
        This function is executed in a separate timer thread and must be
        thread-safe. It performs atomic queue insertion operation.

    Example:
        >>> # Usually called via threading.Timer, not directly
        >>> timer = threading.Timer(300, insert_after_time, args=(queue, fanfic))
    """
    # Perform atomic queue insertion for multiprocessing safety
    queue.put(fanfic)


def process_fanfic(
    fanfic: fanfic_info.FanficInfo,
    ingress_queue: mp.Queue,
) -> None:
    """Processes a failed fanfiction by scheduling delayed retry via timer.

    Schedules delayed retry for fanfictions that have been routed to the waiting
    queue by url_worker after failure. Uses the retry decision that was already
    made and stored in the fanfic object to determine delay timing and logging.

    This function assumes the retry decision has already been made by url_worker
    and stored in fanfic.retry_decision. It focuses solely on implementing the
    delay timing and timer scheduling.

    Args:
        fanfic (fanfic_info.FanficInfo): The fanfiction metadata object containing
                                        URL, site information, current retry state,
                                        and the pre-calculated retry decision.
        ingress_queue (mp.Queue): The queue to insert the fanfiction into after delay.

    Note:
        This function starts a daemon timer thread that will execute independently.
        The timer thread will call insert_after_time() when the delay expires.
        Multiple timers can run concurrently for different fanfictions.
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

    # Log the delay and schedule timer
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

    # Convert delay to seconds and schedule timer
    delay_seconds = int(decision.delay_minutes * 60)
    timer = threading.Timer(
        delay_seconds, insert_after_time, args=(ingress_queue, fanfic)
    )
    timer.start()


def wait_processor(ingress_queue: mp.Queue, waiting_queue: mp.Queue) -> None:
    """Main waiting queue processor for handling delayed fanfiction retries.

    Continuously monitors the waiting queue for failed fanfiction entries that
    need delayed retry processing. Implements the waiting queue component of
    the retry protocol by receiving failed fanfictions and scheduling their
    delayed reprocessing via the pre-calculated retry decisions.

    This function runs in a dedicated process and processes entries from the
    waiting queue in a continuous loop. Each failed fanfiction is processed
    via process_fanfic() which uses the pre-calculated retry decision to
    schedule timer-based requeuing back to the ingress queue.

    Args:
        ingress_queue (mp.Queue): The single ingress queue for all tasks.
        waiting_queue (mp.Queue): The shared multiprocessing queue containing
                                 failed fanfiction entries awaiting delayed retry.
                                 Supports poison pill (None) shutdown pattern.

    Note:
        This function runs indefinitely until a None entry (poison pill) is
        received in the waiting queue, which signals graceful shutdown. The
        5-second sleep prevents busy-waiting and reduces CPU usage.

    Shutdown:
        The function supports graceful shutdown via poison pill pattern. When
        ProcessManager needs to stop this worker, it sends None to the queue,
        causing the function to break from its processing loop and return.

    Example:
        >>> # Typically called by ProcessManager in separate process
        >>> wait_processor(ingress_queue, waiting_queue)
    """
    while True:
        # Block waiting for next failed fanfiction entry from waiting queue
        fanfic: fanfic_info.FanficInfo = waiting_queue.get()

        # Check for poison pill shutdown signal (None entry)
        if fanfic is None:
            break

        # Schedule delayed retry processing for the failed fanfiction
        process_fanfic(fanfic, ingress_queue)

        # Brief sleep to prevent busy-waiting and reduce CPU usage
        sleep(5)  # Sleep for 5 seconds between processing iterations
