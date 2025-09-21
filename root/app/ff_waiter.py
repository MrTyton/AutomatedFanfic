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
import random
import threading
from time import sleep

import fanfic_info
import ff_logging


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
    fanfic: fanfic_info.FanficInfo, processor_queues: dict[str, mp.Queue]
) -> None:
    """Processes a failed fanfiction by scheduling delayed retry via timer.

    Implements gradual backoff with random jitter for failed fanfiction
    downloads as part of the Hail-Mary protocol. Calculates retry delay using
    a gradual increase with jitter to prevent thundering herd effects when
    multiple retries occur simultaneously.

    The delay calculation uses gradual backoff with jitter:
    base_delay = min(60 * retry_count, 1200)  # 1min per retry, capped at 20 minutes
    jitter = random.uniform(0.5, 1.5)  # ±50% random jitter
    final_delay = base_delay * jitter

    This provides gradual growth (1min, 2min, 3min, 4min, 5min, etc.) up to
    20 minutes maximum, with randomization to spread out retry attempts.

    Args:
        fanfic (fanfic_info.FanficInfo): The fanfiction metadata object containing
                                        URL, site information, and retry state
                                        including the repeat count for delay calculation.
        processor_queues (dict[str, mp.Queue]): Dictionary mapping site names to
                                                their corresponding processing queues.
                                                Used to route the fanfiction back to
                                                the correct site-specific worker.

    Note:
        This function starts a daemon timer thread that will execute independently.
        The timer thread will call insert_after_time() when the delay expires.
        Multiple timers can run concurrently for different fanfictions.

    Example:
        >>> fanfic = FanficInfo(url="...", repeats=10)  # 10th retry
        >>> process_fanfic(fanfic, {"archiveofourown.org": queue})
        # Will log "Waiting ~18.3 minutes..." and schedule requeue in ~1098 seconds
    """
    retry_count = fanfic.repeats or 0  # Default to 0 if repeats is None

    # Calculate gradual backoff with maximum cap of 20 minutes (1200 seconds)
    # 1 minute per retry: 1min, 2min, 3min, 4min, 5min... up to 20min
    base_delay = min(60 * retry_count, 1200)

    # Add random jitter (±50% variation) to prevent thundering herd
    jitter_multiplier = random.uniform(0.5, 1.5)
    delay = int(base_delay * jitter_multiplier)

    # Convert to minutes for cleaner logging
    delay_minutes = delay / 60.0

    # Log the retry delay with warning level for visibility
    ff_logging.log(
        f"Waiting ~{delay_minutes:.2f} minutes for {fanfic.url} in queue {fanfic.site} "
        f"(retry #{retry_count + 1}, base: {base_delay//60}min, jitter: {jitter_multiplier:.2f}x)",
        "WARNING",
    )
    # Create and start timer thread for delayed requeuing
    timer = threading.Timer(
        delay, insert_after_time, args=(processor_queues[fanfic.site], fanfic)
    )
    timer.start()


def wait_processor(
    processor_queues: dict[str, mp.Queue], waiting_queue: mp.Queue
) -> None:
    """Main waiting queue processor for handling delayed fanfiction retries.

    Continuously monitors the waiting queue for failed fanfiction entries that
    need delayed retry processing. Implements the waiting queue component of
    the Hail-Mary protocol by receiving failed fanfictions, scheduling their
    delayed reprocessing, and managing graceful shutdown.

    This function runs in a dedicated process and processes entries from the
    waiting queue in a continuous loop. Each failed fanfiction is processed
    via process_fanfic() which calculates appropriate delays and schedules
    timer-based requeuing back to site-specific processing queues.

    Args:
        processor_queues (dict[str, mp.Queue]): Dictionary mapping fanfiction
                                               site names (e.g., "archiveofourown.org")
                                               to their corresponding multiprocessing
                                               queues for site-specific processing.
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
        >>> site_queues = {"archiveofourown.org": queue1, "fanfiction.net": queue2}
        >>> wait_processor(site_queues, waiting_queue)
    """
    while True:
        # Block waiting for next failed fanfiction entry from waiting queue
        fanfic: fanfic_info.FanficInfo = waiting_queue.get()

        # Check for poison pill shutdown signal (None entry)
        if fanfic is None:
            break

        # Schedule delayed retry processing for the failed fanfiction
        process_fanfic(fanfic, processor_queues)

        # Brief sleep to prevent busy-waiting and reduce CPU usage
        sleep(5)  # Sleep for 5 seconds between processing iterations
