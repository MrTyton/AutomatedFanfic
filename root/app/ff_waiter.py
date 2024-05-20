import multiprocessing as mp
import threading
from time import sleep

import fanfic_info
import ff_logging

def insert_after_time(queue: mp.Queue, fanfic: fanfic_info.FanficInfo) -> None:
    """
    Inserts a fanfic into the queue after a delay.

    Args:
        queue (mp.Queue): The queue to insert the fanfic into.
        fanfic (fanfic_info.FanficInfo): The fanfic to insert.
    """
    # Insert the fanfic into the queue
    queue.put(fanfic)

def process_fanfic(fanfic: fanfic_info.FanficInfo, processor_queues: dict[str, mp.Queue]) -> threading.Timer:
    """
    Processes a single fanfic. It calculates a delay based on the number of repeats for the fanfic,
    logs a warning message, and starts a timer to insert the fanfic into the appropriate processor queue after the delay.

    Args:
        fanfic (fanfic_info.FanficInfo): The fanfic to process.
        processor_queues (dict[str, mp.Queue]): A dictionary of processor queues.

    Returns:
        threading.Timer: The timer that was started.
    """
    # Calculate the delay based on the number of repeats for the fanfic
    delay = 60 * fanfic.repeats
    # Log a warning message indicating that we're waiting for a certain delay
    ff_logging.log(f"Waiting {fanfic.repeats} minutes for {fanfic.url} in queue {fanfic.site}", "WARNING")
    # Start a timer to insert the fanfic into the appropriate processor queue after the delay
    timer = threading.Timer(delay, insert_after_time, args=(processor_queues[fanfic.site], fanfic))
    timer.start()

    return timer

def wait_processor(processor_queues: dict[str, mp.Queue], waiting_queue: mp.Queue):
    """
    Processes the waiting queue.

    Args:
        processor_queues (dict[str, mp.Queue]): A dictionary of processor queues.
        waiting_queue (mp.Queue): The waiting queue.
    """
    while True:
        # Get a fanfic from the waiting queue
        fanfic: fanfic_info.FanficInfo = waiting_queue.get()

        # If the fanfic is None, this signals that we should stop processing the waiting queue
        if fanfic is None:
            break

        # Process the fanfic
        process_fanfic(fanfic, processor_queues)
        
        sleep(5)  # Sleep for 5 seconds to avoid busy-waiting
