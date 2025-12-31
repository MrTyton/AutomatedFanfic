"""
Coordinator for AutomatedFanfic Worker Pool

This module implements the central coordinator that manages task distribution
and concurrency control for the worker pool. It ensures that:
1. Tasks are distributed to available workers
2. No two workers process the same site/domain simultaneously (Domain Locking)
3. Workers are kept busy while respecting site rate limits/locks
"""

import multiprocessing as mp
import collections
from typing import Dict, Set, Optional
from queue import Empty
from utils import ff_logging
from models.fanfic_info import FanficInfo


class Coordinator:
    def __init__(self, ingress_queue: mp.Queue, worker_queues: Dict[str, mp.Queue]):
        self.ingress_queue = ingress_queue
        self.worker_queues = worker_queues

        # Backlog: Ordered list of tasks per site
        # { 'fanfiction': deque([task1, task2]), 'ao3': deque([task3]) }
        self.backlog: Dict[str, collections.deque] = collections.defaultdict(
            collections.deque
        )

        # Assignments: Maps site -> worker_id tracking which worker owns a site
        self.assignments: Dict[str, str] = {}

        # Idle Workers: Set of worker_ids that are not currently assigned a site
        # Initialize with all workers as they start idle
        self.idle_workers: Set[str] = set(worker_queues.keys())

        # Shutdown flag
        self.running = True

    def run(self):
        """Main coordinator loop."""
        ff_logging.log("Coordinator started", "HEADER")

        while self.running:
            # Process incoming events (tasks or signals)
            # Use a timeout to prevent busy waiting while keeping the loop responsive
            # and allowing for periodic tasks or shutdown checks if needed.
            # 1.0s timeout is a good balance between responsiveness and efficiency.
            try:
                # Wait for next item or timeout
                # This blocks efficiently without consuming CPU
                self._process_single_ingress_item(timeout=1.0)
            except Exception as e:
                ff_logging.log_failure(f"Coordinator: Error in main loop: {e}")

    def _process_single_ingress_item(self, timeout: float):
        """
        Wait for and handle a single item from the ingress queue.

        Args:
            timeout (float): Max seconds to wait for an item.
        """
        try:
            item = self.ingress_queue.get(timeout=timeout)

            if item is None:
                # Poison pill received
                ff_logging.log("Coordinator received shutdown signal", "WARNING")
                self.running = False
                return

            # Check if it's a Signal or a Task
            if isinstance(item, tuple) and len(item) == 3 and item[0] == "WORKER_IDLE":
                # Signal: ('WORKER_IDLE', worker_id, finished_site)
                _, worker_id, finished_site = item
                self._handle_worker_idle(worker_id, finished_site)
            elif type(item).__name__ == "FanficInfo":
                # Task: FanficInfo object
                self._handle_new_task(item)
            else:
                ff_logging.log_failure(
                    f"Coordinator: Received invalid item type {type(item)}"
                )

        except Empty:
            # Timeout reached, just return so main loop can check running state
            pass
        except Exception as e:
            ff_logging.log_failure(f"Coordinator: Error processing ingress: {e}")

    def _handle_new_task(self, task: FanficInfo):
        """Route new task to appropriate worker or backlog."""
        site = task.site

        # 1. If site is already assigned to a worker, push directly
        if site in self.assignments:
            worker_id = self.assignments[site]
            self.worker_queues[worker_id].put(task)
            ff_logging.log_debug(
                f"Coordinator: Direct push {task.url} to {worker_id} (Site: {site})"
            )
            return

        # 2. Site is not active. Add to backlog.
        self.backlog[site].append(task)
        ff_logging.log_debug(f"Coordinator: Added {task.url} to backlog (Site: {site})")

        # 3. Try to assign immediately if we have waiting workers
        self._assign_work_if_possible()

    def _handle_worker_idle(self, worker_id: str, finished_site: Optional[str]):
        """Handle worker reporting idle status."""
        # Mark worker as idle
        self.idle_workers.add(worker_id)

        # If worker was assigned a site, release it (since they are only idle if queue is empty)
        if finished_site and finished_site in self.assignments:
            # Verify this worker actually owns it (paranoia check)
            if self.assignments[finished_site] == worker_id:
                del self.assignments[finished_site]
                ff_logging.log_debug(
                    f"Coordinator: Worker {worker_id} finished site {finished_site}. Lock released."
                )
            else:
                ff_logging.log(
                    f"Coordinator: Worker {worker_id} claimed finish for {finished_site} but assigned to {self.assignments[finished_site]}",
                    "WARNING",
                )

        # Try to give this worker (and others) new work
        self._assign_work_if_possible()

    def _assign_work_if_possible(self):
        """Assign pending backlog items to idle workers."""
        if not self.idle_workers:
            return

        # Simple greedy assignment: Give queued sites to free workers
        # We make a copy since we might modify the set during iteration
        available_workers = list(self.idle_workers)

        for worker_id in available_workers:
            # Find a site in backlog that is NOT currently assigned
            candidate_site = None
            for site in list(self.backlog.keys()):
                if site not in self.assignments and self.backlog[site]:
                    candidate_site = site
                    break

            if candidate_site:
                # Assign site to worker
                self.assignments[candidate_site] = worker_id
                self.idle_workers.remove(worker_id)
                ff_logging.log_debug(
                    f"Coordinator: Assigned {candidate_site} to {worker_id}"
                )

                # Drain ENTIRE backlog for this site to the worker
                queue = self.worker_queues[worker_id]
                count = 0
                while self.backlog[candidate_site]:
                    task = self.backlog[candidate_site].popleft()
                    queue.put(task)
                    count += 1

                # Cleanup empty backlog entry
                del self.backlog[candidate_site]
                ff_logging.log_debug(
                    f"Coordinator: Pushed {count} tasks for {candidate_site} to {worker_id}"
                )

            else:
                # No eligible work found within backlog
                break


def start_coordinator(ingress_queue: mp.Queue, worker_queues: Dict[str, mp.Queue]):
    """Entry point for the coordinator process."""
    coordinator = Coordinator(ingress_queue, worker_queues)
    try:
        coordinator.run()
    except KeyboardInterrupt:
        ff_logging.log("Coordinator stopped by KeyboardInterrupt")
    except Exception as e:
        ff_logging.log_failure(f"Coordinator crashed: {e}")
