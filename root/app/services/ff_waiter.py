"""Delayed processing module for failed fanfiction downloads.

This module implements the AutomatedFanfic waiting queue system for handling
failed fanfiction downloads that need to be retried after exponential backoff
delays. It provides heap-scheduled delayed requeuing functionality as part of
the Hail-Mary protocol for story processing failures.

Key Features:
    - Heap-based delayed fanfiction reprocessing (single scheduler thread)
    - Exponential backoff delay calculation based on retry counts
    - Integration with site-specific processing queues
    - Graceful shutdown support via poison pill pattern and shutdown_event

Functions:
    _log_retry_decision: Logs retry decision details for a fanfic.
    _get_delay_seconds: Extracts delay from a fanfic's retry decision.
    wait_processor: Main waiting queue processor with heap-based scheduling.

Architecture:
    The module works with the broader multiprocessing architecture by receiving
    failed fanfiction entries in a waiting queue, calculating appropriate retry
    delays based on failure counts, and using a heap-based scheduler to
    requeue items back to the ingress queue after the delay period expires.

    Previous versions used one threading.Timer per failed fanfic, which could
    accumulate hundreds of threads under sustained failure conditions. The
    current implementation uses a single-threaded heapq scheduler, reducing
    thread count from O(N_failures) to O(1).

Example:
    >>> # Used by ProcessManager to start waiting queue processor
    >>> wait_processor(ingress_queue, waiting_queue)
"""

import heapq
import multiprocessing as mp
import threading
import time

from models import fanfic_info
from utils import ff_logging
from models import retry_types


def _log_retry_decision(
    fanfic: fanfic_info.FanficInfo,
    decision: retry_types.RetryDecision,
) -> None:
    """Log details about a retry decision for a fanfic.

    Args:
        fanfic: The fanfiction metadata object.
        decision: The retry decision containing action and delay info.
    """
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
        ff_logging.log(
            f"Unexpected {decision.action.value} action in waiting queue for {fanfic.url}. "
            f"Abandoning processing.",
            "ERROR",
        )


def _get_delay_seconds(fanfic: fanfic_info.FanficInfo) -> int | None:
    """Extract delay in seconds from a fanfic's retry decision, logging as needed.

    Handles missing decisions with a fallback and rejects ABANDON actions.

    Args:
        fanfic: The fanfiction metadata object with retry_decision attached.

    Returns:
        Delay in seconds, or None if the item should be dropped (ABANDON action).
    """
    decision = fanfic.retry_decision
    if decision is None:
        ff_logging.log(
            f"No retry decision found for {fanfic.url}. Using default retry action.",
            "WARNING",
        )
        decision = retry_types.RetryDecision(
            action=retry_types.FailureAction.RETRY,
            delay_minutes=5.0,
            should_notify=False,
            notification_message="",
        )
        fanfic.retry_decision = decision

    _log_retry_decision(fanfic, decision)

    if decision.action not in (
        retry_types.FailureAction.RETRY,
        retry_types.FailureAction.HAIL_MARY,
    ):
        return None

    return int(decision.delay_minutes * 60)


def wait_processor(
    ingress_queue: mp.Queue,
    waiting_queue: mp.Queue,
    verbose: bool = False,
    shutdown_event: threading.Event = None,
    history_recorder=None,
) -> None:
    """Main waiting queue processor for handling delayed fanfiction retries.

    Continuously monitors the waiting queue for failed fanfiction entries and
    schedules their reprocessing using a heap-based delay scheduler. Items are
    requeued to the ingress queue once their delay expires.

    Uses a single heapq instead of per-item threading.Timer threads, keeping
    thread count at O(1) regardless of failure volume.

    Args:
        ingress_queue (mp.Queue): The single ingress queue for all tasks.
        waiting_queue (mp.Queue): The shared multiprocessing queue containing
                                 failed fanfiction entries awaiting delayed retry.
                                 Supports poison pill (None) shutdown pattern.
        verbose (bool): Enable verbose logging.
        shutdown_event (threading.Event, optional): Event to signal shutdown.
    """
    ff_logging.set_verbose(verbose)
    ff_logging.set_thread_color("\033[96m")  # Bright Cyan

    # Heap entries: (expiry_time, sequence_counter, fanfic)
    # sequence_counter breaks ties so FanficInfo never needs to be compared.
    pending_heap: list[tuple[float, int, fanfic_info.FanficInfo]] = []
    seq = 0

    while True:
        # Check for shutdown signal
        if shutdown_event and shutdown_event.is_set():
            ff_logging.log_debug("Waiter received shutdown signal")
            break

        # --- Drain expired items from the heap ---
        now = time.monotonic()
        while pending_heap and pending_heap[0][0] <= now:
            _, _, fanfic = heapq.heappop(pending_heap)
            ingress_queue.put(fanfic)
            if history_recorder:
                history_recorder.record_retry_fired(fanfic.url, fanfic.repeats or 0)

        # --- Calculate how long we can sleep ---
        if pending_heap:
            sleep_until_next = max(0.0, pending_heap[0][0] - time.monotonic())
            # Don't sleep longer than 2s so we stay responsive to new items / shutdown
            queue_timeout = min(sleep_until_next, 2.0)
        else:
            queue_timeout = 2.0

        # --- Check waiting_queue for new failed items ---
        try:
            fanfic_item: fanfic_info.FanficInfo = waiting_queue.get(
                timeout=queue_timeout
            )
        except Exception:  # queue.Empty is expected on timeout
            continue

        # Poison pill shutdown
        if fanfic_item is None:
            break

        # Schedule the item on the heap
        delay = _get_delay_seconds(fanfic_item)
        if delay is None:
            continue  # ABANDON — drop the item

        expiry = time.monotonic() + delay
        heapq.heappush(pending_heap, (expiry, seq, fanfic_item))
        seq += 1
