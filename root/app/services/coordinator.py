"""
Coordinator for AutomatedFanfic Worker Pool

This module implements the central coordinator that manages task distribution
and concurrency control for the worker pool. It ensures that:
1. Tasks are distributed to available workers
2. No two workers process the same site/domain simultaneously (Domain Locking)
3. Workers are kept busy while respecting site rate limits/locks

Architecture Note:
    The coordinator communicates with workers through the ingress_queue, which serves
    dual purposes:
    1. Receives FanficInfo tasks to be distributed
    2. Receives worker signals (WORKER_IDLE tuples) when workers complete sites

    Workers signal completion by putting ('WORKER_IDLE', worker_id, finished_site)
    back into the ingress_queue. This is the same queue used by failure handlers
    for retries, creating a unified task ingress point.
"""

import collections
from collections.abc import MutableMapping
from dataclasses import dataclass, field

from queue import Empty
from enum import Enum
from config.config_store import ConfigStore
from history.recorder import HistoryRecorder
from utils import ff_logging
from models import active_urls as active_urls_utils
from models.active_urls import ActiveUrlsDict
from models.fanfic_info import FanficInfo
from models.queue_types import (
    IngressQueue,
    ScaleQueue,
    ShutdownEvent,
    WorkerQueue,
    WorkerQueues,
)

lazy from utils import series_utils
lazy from parsers import regex_parsing

_MAX_SERIES_DEPTH: int = 10


class SignalType(Enum):
    """Types of signals that can be sent to the coordinator."""

    WORKER_IDLE = "WORKER_IDLE"
    WORKER_STOPPED = "WORKER_STOPPED"
    SHUTDOWN = "SHUTDOWN"


@dataclass
class WorkerSignal:
    """Represents a signal from a worker to the coordinator."""

    signal_type: SignalType
    worker_id: str
    site: str | None = None

    @classmethod
    def from_tuple(cls, signal_tuple: tuple) -> "WorkerSignal | None":
        """Create WorkerSignal from legacy tuple format for backward compatibility."""
        if not isinstance(signal_tuple, tuple) or len(signal_tuple) < 2:
            return None

        signal_str = signal_tuple[0]
        if signal_str == "WORKER_IDLE" and len(signal_tuple) == 3:
            return cls(
                signal_type=SignalType.WORKER_IDLE,
                worker_id=signal_tuple[1],
                site=signal_tuple[2],
            )
        if signal_str == "WORKER_STOPPED" and len(signal_tuple) >= 2:
            return cls(
                signal_type=SignalType.WORKER_STOPPED,
                worker_id=signal_tuple[1],
                site=signal_tuple[2] if len(signal_tuple) > 2 else None,
            )
        return None


@dataclass
class CoordinatorState:
    """Encapsulates the internal state of the coordinator.

    This dataclass groups related state variables together for clearer
    state management and easier testing.
    """

    backlog: dict[str, collections.deque] = field(
        default_factory=lambda: collections.defaultdict(collections.deque)
    )
    assignments: dict[str, str] = field(default_factory=dict)
    idle_workers: set[str] = field(default_factory=set)
    dormant_workers: set[str] = field(default_factory=set)
    qsize_supported: bool = True  # Cache whether queue.qsize() is supported


class Coordinator:
    """Central task coordinator enforcing site-level domain locking across workers.

    Consumes `FanficInfo` tasks and `('WORKER_IDLE', worker_id, site)` signals from
    `ingress_queue`, expands series URLs into individual story URLs when needed,
    buffers tasks per site in `self.state.backlog`, and assigns each site's backlog
    to at most one idle worker at a time.
    """

    def __init__(
        self,
        ingress_queue: IngressQueue,
        worker_queues: WorkerQueues,
        shutdown_event: ShutdownEvent,
        active_urls: ActiveUrlsDict,
        history_recorder: HistoryRecorder,
        url_parsers: dict,
        config_store: ConfigStore,
        scale_queue: ScaleQueue,
        coordinator_status: MutableMapping[str, object] | None = None,
        verbose: bool = False,
    ) -> None:
        """Initialize the Coordinator.

        Args:
            ingress_queue (IngressQueue): Unified queue receiving FanficInfo tasks
                and worker idle signals.
            worker_queues (WorkerQueues): Mapping of worker_id to worker-specific queues.
            shutdown_event (ShutdownEvent): Event signalling graceful shutdown.
            active_urls (MutableMapping[str, Any]): Shared map of active URLs and
                their current status.
            history_recorder (HistoryRecorder): Recorder for persisting download
                creation events (e.g., during series expansion).
            url_parsers (dict): Compiled URL parsers for normalizing and classifying
                story URLs extracted from series pages.
            config_store (ConfigStore): Shared ConfigStore providing FanFicFare
                configuration for series expansion.
            scale_queue (ScaleQueue): Queue for signaling worker pool
                scaling requests.
        """
        self.ingress_queue = ingress_queue
        self.worker_queues = worker_queues
        self.shutdown_event = shutdown_event
        self.active_urls = active_urls
        self.history_recorder = history_recorder
        self.url_parsers = url_parsers
        self.config_store = config_store
        self.scale_queue = scale_queue
        self.coordinator_status = coordinator_status
        self.verbose = verbose

        # Encapsulated coordinator state
        worker_ids = set(worker_queues.keys())
        if "worker_0" in worker_ids:
            idle_workers = {"worker_0"}
            dormant_workers = {w for w in worker_ids if w != "worker_0"}
        else:
            idle_workers = worker_ids
            dormant_workers = set()

        self.state = CoordinatorState(
            idle_workers=idle_workers,
            dormant_workers=dormant_workers,
        )

        # Check if qsize() is supported once at startup
        self._check_qsize_support()

        # Shutdown flag
        self.running = True

        # Publish initial state
        self._publish_state()

    def _publish_state(self) -> None:
        """Snapshot internal assignments, worker states, and backlogs to shared state."""
        if self.coordinator_status is None:
            return
        try:
            backlog_snapshot = {
                site: [
                    {
                        "url": getattr(task, "url", str(task)),
                        "site": getattr(task, "site", site),
                        "repeats": getattr(task, "repeats", 0),
                        "repeat_count": getattr(task, "repeats", 0) or 0,
                        "calibre_id": getattr(task, "calibre_id", None),
                        "behavior": getattr(task, "behavior", None),
                        "title": getattr(task, "title", None),
                    }
                    for task in deque
                ]
                for site, deque in self.state.backlog.items()
                if deque
            }
            self.coordinator_status["assignments"] = dict(self.state.assignments)
            self.coordinator_status["idle_workers"] = sorted(self.state.idle_workers)
            self.coordinator_status["dormant_workers"] = sorted(
                self.state.dormant_workers
            )
            self.coordinator_status["backlog"] = backlog_snapshot
        except Exception as e:
            ff_logging.log_debug(f"Coordinator: Suppressed error publishing state: {e}")

    def get_state_snapshot(self) -> dict:
        """Return a serialisable snapshot of the coordinator's internal state."""
        backlog_snapshot = {}
        for site, deque in self.state.backlog.items():
            backlog_snapshot[site] = [f.url for f in deque]
        return {
            "backlog": backlog_snapshot,
            "assignments": dict(self.state.assignments),
            "idle_workers": sorted(self.state.idle_workers),
            "dormant_workers": sorted(self.state.dormant_workers),
        }

    def _check_qsize_support(self) -> None:
        """Check if queue.qsize() is supported on this platform."""
        try:
            # Test with any worker queue
            queue_values = list(self.worker_queues.values())
            if queue_values:
                queue_values[0].qsize()
                self.state.qsize_supported = True
        except NotImplementedError:
            self.state.qsize_supported = False
            ff_logging.log_debug("Queue.qsize() not supported on this platform")

    def run(self):
        """Main coordinator loop."""
        ff_logging.log_debug("Coordinator started")

        while self.running:
            # Check for external shutdown signal (if provided)
            if self.shutdown_event and self.shutdown_event.is_set():
                ff_logging.log_debug("Coordinator received shutdown signal")
                break

            try:
                self._process_single_ingress_item(timeout=None)
            except Exception as e:
                ff_logging.log_failure(f"Coordinator: Error in main loop: {e}")

        self._log_and_drain_backlog_on_shutdown()

    def _log_and_drain_backlog_on_shutdown(self) -> None:
        """Log a warning and requeue pending backlog tasks to ingress_queue on shutdown.

        URLs already recorded in active_urls as "queued" will be recovered on the
        next startup if resume_uncompleted_on_startup is enabled. Requeuing them
        ensures that coordinator process restarts resume backlog seamlessly.
        """
        for site in list(self.state.backlog):
            tasks = self.state.backlog[site]
            if not tasks:
                continue
            urls = [t.url for t in tasks]
            ff_logging.log_failure(
                f"Coordinator: Shutdown with {len(tasks)} queued task(s) "
                f"for site '{site}' — requeuing to ingress_queue for restart: {urls}"
            )
            while tasks:
                task = tasks.popleft()
                try:
                    self.ingress_queue.put(task)
                except Exception as e:
                    ff_logging.log_failure(
                        f"Coordinator: Failed to requeue task {task.url}: {e}"
                    )
        self._publish_state()

    def _process_single_ingress_item(self, timeout: float | None = None):
        """
        Wait for and handle a single item from the ingress queue.

        Args:
            timeout (float | None): Max seconds to wait for an item.
                When None, performs a blocking wait.
        """
        try:
            if timeout is None:
                item = self.ingress_queue.get()
            else:
                item = self.ingress_queue.get(timeout=timeout)

            if item is None:
                # Poison pill received
                ff_logging.log("Coordinator received shutdown signal", "WARNING")
                self.running = False
                return

            # Handle worker signals (tuple format for backward compatibility)
            if isinstance(item, tuple):
                signal = WorkerSignal.from_tuple(item)
                if signal and signal.signal_type == SignalType.WORKER_IDLE:
                    self._handle_worker_idle(signal.worker_id, signal.site)
                    return
                if signal and signal.signal_type == SignalType.WORKER_STOPPED:
                    self._handle_worker_stopped(signal.worker_id)
                    return

            # Handle task
            if isinstance(item, FanficInfo):
                self._handle_new_task(item, 0)
            else:
                ff_logging.log_failure(
                    f"Coordinator: Received invalid item type {type(item)}"
                )

        except OSError as e:
            ff_logging.log_failure(f"Coordinator: Error processing ingress: {e}")
        except Empty:
            # Timeout path used by targeted tests and optional timeout callers.
            pass

    def _handle_new_task(self, task: FanficInfo, depth: int = 0):
        """Route new task to appropriate worker or backlog.

        Automatically detects and expands series/collection URLs into individual
        story tasks before routing.
        """
        if depth >= _MAX_SERIES_DEPTH:
            ff_logging.log_failure(
                f"Coordinator: Aborting series expansion — max depth {_MAX_SERIES_DEPTH} "
                f"reached for {task.url} (possible circular series reference)"
            )
            return
        # Check if the task was cancelled before routing or expanding
        if self.active_urls is not None:
            try:
                meta = dict(self.active_urls.get(task.url, {}))
                if meta.get("status") == "cancelled":
                    active_urls_utils.remove_active_url(self.active_urls, task.url)
                    ff_logging.log_debug(
                        f"Coordinator: Dropped cancelled task {task.url}"
                    )
                    return
            except Exception as e:
                ff_logging.log_debug(
                    f"Coordinator: Suppressed active_urls read error in _handle_new_task: {e}"
                )

        site = task.site

        # Check if this is a series/collection URL
        expansion_result = series_utils.process_url(
            task.url,
            config_store=self.config_store,
        )

        if expansion_result["is_series"]:
            if expansion_result["count"] > 1 or (
                expansion_result["count"] == 1
                and expansion_result["urls"]
                and expansion_result["urls"][0] != task.url
            ):
                # Expand series into individual story tasks
                ff_logging.log(
                    f"Coordinator: Expanding series ({expansion_result['count']} stories): {task.url}"
                )

                # Remove the parent series URL from active_urls since workers only
                # process and clean up the individual child story URLs.
                active_urls_utils.remove_active_url(self.active_urls, task.url)
            elif expansion_result["count"] == 0:
                # Detected as series, but expansion produced 0 stories (e.g. 403 or network error)
                ff_logging.log_failure(
                    f"Coordinator: Failed to expand series {task.url} into story URLs"
                )
                active_urls_utils.mark_url_failed(
                    self.active_urls,
                    task.url,
                    "Failed to expand series (check credentials/login in personal.ini or network)",
                )
                return

            for story_url in expansion_result["urls"]:
                child_url = story_url
                child_site = site
                if self.url_parsers:
                    try:
                        parsed = regex_parsing.generate_FanficInfo_from_url(
                            story_url, self.url_parsers
                        )
                        child_url = parsed.url
                        if parsed.site and parsed.site != "other":
                            child_site = parsed.site
                    except Exception as e:
                        ff_logging.log_debug(
                            f"Coordinator: Suppressed URL parser error for {story_url}: {e}"
                        )

                story_task = FanficInfo(
                    url=child_url,
                    site=child_site,
                    calibre_id=task.calibre_id,
                    behavior=task.behavior,
                    title=None,
                    repeats=0,  # Individual stories start fresh, never inherit series repeats
                    retry_decision=task.retry_decision,
                    from_email=task.from_email,
                )
                active_urls_utils.mark_url_queued(
                    self.active_urls, story_task.url, site=story_task.site
                )
                if self.history_recorder is not None:
                    try:
                        self.history_recorder.record_download_created(
                            story_task.url, story_task.site, story_task.behavior
                        )
                    except Exception as e:
                        ff_logging.log_debug(
                            f"Coordinator: Suppressed history recorder error for {story_task.url}: {e}"
                        )
                self._handle_new_task(story_task, depth + 1)

            return

        # 1. If site is already assigned to a worker, push directly
        if site in self.state.assignments:
            worker_id = self.state.assignments[site]
            queue = self.worker_queues[worker_id]
            queue.put(task)

            pos_str = self._get_queue_position_string(queue)
            ff_logging.log_debug(
                f"Coordinator: Routed {task.url} to {worker_id} (Site: {site}, {pos_str})"
            )
            return

        # 2. Site is not active. Add to backlog.
        self.state.backlog[site].append(task)
        ff_logging.log_debug(f"Coordinator: Added {task.url} to backlog (Site: {site})")
        self._publish_state()

        # 3. Try to assign immediately if we have waiting workers
        self._assign_work_if_possible()

    def _get_queue_position_string(self, queue: WorkerQueue) -> str:
        """Get queue position string, using cached qsize support detection."""
        if self.state.qsize_supported:
            try:
                return f"Queue Pos: {queue.qsize()}"
            except NotImplementedError:
                # Update cache if we discover qsize isn't supported
                self.state.qsize_supported = False
                return "Queue Pos: Unknown"
        return "Queue Pos: Unknown"

    def _handle_worker_idle(self, worker_id: str, finished_site: str | None):
        """Handle worker reporting idle status."""
        # Mark worker as idle
        self.state.idle_workers.add(worker_id)

        # If worker was assigned a site, release it (since they are only idle if queue is empty)
        if finished_site and finished_site in self.state.assignments:
            # Verify this worker actually owns it (paranoia check)
            if self.state.assignments[finished_site] == worker_id:
                del self.state.assignments[finished_site]
                ff_logging.log_debug(
                    f"Coordinator: Worker {worker_id} finished site {finished_site}. Lock released.",
                )
            else:
                ff_logging.log(
                    f"Coordinator: Worker {worker_id} claimed finish for {finished_site} but assigned to {self.state.assignments[finished_site]}",
                    "WARNING",
                )

        # Try to give this worker (and others) new work
        self._assign_work_if_possible()

    def _handle_worker_stopped(self, worker_id: str) -> None:
        """Handle worker reporting it has stopped and exited."""
        self.state.idle_workers.discard(worker_id)
        assigned_sites = [
            site for site, w in self.state.assignments.items() if w == worker_id
        ]
        for site in assigned_sites:
            del self.state.assignments[site]
            ff_logging.log_debug(
                f"Coordinator: Released stale assignment {site} for stopped {worker_id}"
            )
        self.state.dormant_workers.add(worker_id)
        ff_logging.log_debug(
            f"Coordinator: Worker {worker_id} stopped and marked dormant"
        )
        self._publish_state()

    def _find_unassigned_site(self) -> str | None:
        """Find a site in backlog that is not currently assigned to any worker."""
        for site in self.state.backlog:
            if site not in self.state.assignments and self.state.backlog[site]:
                return site
        return None

    def _drain_site_backlog(self, site: str, queue: WorkerQueue) -> list:
        """Drain all tasks for a site from backlog to worker queue."""
        tasks_pushed = []
        while self.state.backlog[site]:
            task = self.state.backlog[site].popleft()
            if self.active_urls is not None:
                try:
                    meta = dict(self.active_urls.get(task.url, {}))
                    if meta.get("status") == "cancelled":
                        active_urls_utils.remove_active_url(self.active_urls, task.url)
                        ff_logging.log_debug(
                            f"Coordinator: Dropped cancelled backlog task {task.url}"
                        )
                        continue
                except Exception as e:
                    ff_logging.log_debug(
                        f"Coordinator: Suppressed active_urls read error in _drain_site_backlog: {e}"
                    )
            queue.put(task)
            tasks_pushed.append(task)

        # Cleanup empty backlog entry
        del self.state.backlog[site]
        return tasks_pushed

    def _log_assignment_details(
        self, site: str, worker_id: str, queue: WorkerQueue, tasks_pushed: list
    ):
        """Log detailed information about the assignment."""
        # Get final queue size to calculate positions
        if self.state.qsize_supported:
            try:
                final_q_size = queue.qsize()
                start_pos = final_q_size - len(tasks_pushed) + 1
            except NotImplementedError:
                self.state.qsize_supported = False
                final_q_size = "Unknown"
                start_pos = None
        else:
            final_q_size = "Unknown"
            start_pos = None

        # Detailed logging of what was pushed
        ff_logging.log_debug(
            f"Coordinator: Assigned {len(tasks_pushed)} task(s) for {site} to {worker_id}:"
        )
        for offset, task in enumerate(tasks_pushed):
            pos_info = (
                f"Pos: {start_pos + offset}"
                if start_pos is not None
                else "Pos: Unknown"
            )
            ff_logging.log_debug(f"  - {task.url} ({pos_info})")

    def _assign_work_if_possible(self):
        """Assign pending backlog items to idle workers."""
        if self.coordinator_status and bool(
            self.coordinator_status.get("paused", False)
        ):
            return

        # Simple greedy assignment: Give queued sites to free workers
        # We make a copy since we might modify the set during iteration
        available_workers = list(self.state.idle_workers)

        for worker_id in available_workers:
            # Skip workers that have been removed from worker_queues (scale-down clean-up)
            if worker_id not in self.worker_queues:
                self.state.idle_workers.discard(worker_id)
                continue

            # Find a site in backlog that is NOT currently assigned
            candidate_site = self._find_unassigned_site()

            if candidate_site:
                # Assign site to worker
                self.state.assignments[candidate_site] = worker_id
                self.state.idle_workers.remove(worker_id)
                ff_logging.log_debug(
                    f"Coordinator: Assigned site {candidate_site} to {worker_id}",
                )

                # Drain ENTIRE backlog for this site to the worker
                queue = self.worker_queues[worker_id]
                tasks_pushed = self._drain_site_backlog(candidate_site, queue)

                # Log assignment details
                self._log_assignment_details(
                    candidate_site, worker_id, queue, tasks_pushed
                )
            else:
                # No eligible work found within backlog
                break

        # If there are still unassigned sites in backlog and dormant workers available,
        # activate dormant workers
        if not self.state.idle_workers and self.state.dormant_workers:
            dormant_list = sorted(
                self.state.dormant_workers,
                key=lambda w: (
                    (0, int(w.split("_")[-1])) if w.split("_")[-1].isdigit() else (1, w)
                ),
            )
            for worker_id in dormant_list:
                if worker_id not in self.worker_queues:
                    self.state.dormant_workers.discard(worker_id)
                    continue

                candidate_site = self._find_unassigned_site()
                if candidate_site:
                    self.state.dormant_workers.remove(worker_id)
                    self.state.assignments[candidate_site] = worker_id
                    ff_logging.log_debug(
                        f"Coordinator: Assigned site {candidate_site} to dormant {worker_id}",
                    )
                    queue = self.worker_queues[worker_id]
                    tasks_pushed = self._drain_site_backlog(candidate_site, queue)
                    self._log_assignment_details(
                        candidate_site, worker_id, queue, tasks_pushed
                    )
                    try:
                        self.scale_queue.put(worker_id)
                    except Exception as e:
                        ff_logging.log_failure(
                            f"Coordinator: Failed to signal scale_queue for {worker_id}: {e}"
                        )
                else:
                    break

        self._publish_state()


def start_coordinator(
    ingress_queue: IngressQueue,
    worker_queues: WorkerQueues,
    verbose: bool,
    shutdown_event: ShutdownEvent,
    active_urls: ActiveUrlsDict,
    history_recorder: HistoryRecorder,
    url_parsers: dict,
    config_store: ConfigStore,
    scale_queue: ScaleQueue,
    coordinator_status: MutableMapping[str, object] | None = None,
) -> None:
    """Entry point for the coordinator thread/process.

    Args:
        ingress_queue (IngressQueue): Unified queue receiving FanficInfo tasks
            and worker idle signals.
        worker_queues (WorkerQueues): Mapping of worker_id to worker-specific queues.
        verbose (bool): Enable verbose debug logging.
        shutdown_event (ShutdownEvent): Event signalling graceful shutdown.
        active_urls (MutableMapping[str, Any]): Shared map of active URLs.
        history_recorder (HistoryRecorder): Recorder for history events.
        url_parsers (dict): Compiled URL parsers for series expansion.
        config_store (ConfigStore): Shared ConfigStore instance.
        scale_queue (ScaleQueue): Queue for signaling worker pool
            scaling requests.
    """
    # Initialize logging for this process
    ff_logging.set_verbose(verbose)
    ff_logging.set_thread_color("\033[95m")  # Magenta

    coordinator = Coordinator(
        ingress_queue,
        worker_queues,
        shutdown_event,
        active_urls,
        history_recorder,
        url_parsers,
        config_store,
        scale_queue=scale_queue,
        coordinator_status=coordinator_status,
        verbose=verbose,
    )
    try:
        coordinator.run()
    except KeyboardInterrupt:
        ff_logging.log("Coordinator stopped by KeyboardInterrupt")
    except Exception as e:
        ff_logging.log_failure(f"Coordinator crashed: {e}")
