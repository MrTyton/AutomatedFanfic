"""Process health monitoring and dynamic scaling for ProcessManager."""

import threading
import time
from typing import TYPE_CHECKING

import ff_logging
from process_management.state import ProcessInfo, ProcessState

if TYPE_CHECKING:
    from process_management.manager import ProcessManager


class ProcessMonitor:
    """Monitors child processes, detects crashes, triggers restarts, and scales pools."""

    def __init__(self, manager: "ProcessManager") -> None:
        self.manager = manager
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background monitoring thread if not already running."""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self.run, name="ProcessMonitor", daemon=True
        )
        self._thread.start()
        ff_logging.log_debug("Started process monitoring thread")

    def run(self) -> None:
        """Main monitoring loop running in background thread."""
        ff_logging.log_debug("Process monitoring started")
        process_config = self.manager.process_config

        if not process_config.enable_monitoring:
            ff_logging.log_debug("Process monitoring disabled in configuration")
            return

        shutdown_event = self.manager._shutdown_event
        while not shutdown_event.is_set():
            try:
                current_time = time.time()

                for name, process_info in list(self.manager.processes.items()):
                    if (
                        process_info.last_health_check is None
                        or current_time - process_info.last_health_check
                        >= process_config.health_check_interval
                    ):
                        self.health_check_process(name, process_info, current_time)

                self.sync_process_config_from_store()
                self.check_web_restart_event()
                self.check_supervisor_restart_event()
                self.check_worker_restart_event()
                self.check_worker_scaling()

                shutdown_event.wait(min(5.0, process_config.health_check_interval))

            except Exception as e:
                ff_logging.log_failure(f"Error in process monitoring: {e}")
                shutdown_event.wait(min(5.0, process_config.health_check_interval))

        ff_logging.log_debug("Process monitoring stopped")

    def sync_process_config_from_store(self) -> None:
        """Refresh hot-reloadable ProcessConfig fields from ConfigStore."""
        config_store = self.manager._config_store
        if config_store is None:
            return
        hi = config_store.get("process.health_check_interval")
        if isinstance(hi, (int, float, str)):
            self.manager.process_config.health_check_interval = float(hi)
        st = config_store.get("process.shutdown_timeout")
        if isinstance(st, (int, float, str)):
            self.manager.process_config.shutdown_timeout = float(st)
        mr = config_store.get("process.max_restart_attempts")
        if isinstance(mr, (int, float, str)):
            self.manager.process_config.max_restart_attempts = int(mr)

    def check_web_restart_event(self) -> None:
        """Restart the web server process if the web_restart_event is set."""
        web_event = self.manager._web_restart_event
        if (
            web_event is None
            or not web_event.is_set()
            or "web_server" not in self.manager.processes
        ):
            return
        ff_logging.log("ProcessManager: web config changed, restarting web_server")
        web_event.clear()
        self.manager.processes["web_server"].restart_count = 0
        self.manager.restart_process("web_server")

    def check_supervisor_restart_event(self) -> None:
        """Restart the supervisor process if the supervisor_restart_event is set."""
        sup_event = self.manager._supervisor_restart_event
        if (
            sup_event is None
            or not sup_event.is_set()
            or "supervisor" not in self.manager.processes
        ):
            return
        ff_logging.log("ProcessManager: restart requested, restarting supervisor")
        sup_event.clear()
        self.manager.processes["supervisor"].restart_count = 0
        self.manager.restart_process("supervisor")

    def check_worker_restart_event(self) -> None:
        """Restart the worker pool process if the worker_restart_event is set."""
        worker_event = self.manager._worker_restart_event
        if (
            worker_event is None
            or not worker_event.is_set()
            or "worker_pool" not in self.manager.processes
        ):
            return
        ff_logging.log("ProcessManager: restart requested, restarting worker_pool")
        worker_event.clear()
        self.manager.processes["worker_pool"].restart_count = 0
        self.manager.restart_process("worker_pool")

    def check_worker_scaling(self) -> None:
        """Dynamically add or remove worker queues when max_workers changes in ConfigStore."""
        config_store = self.manager._config_store
        worker_queues = self.manager._worker_queues
        create_queue_fn = self.manager._create_queue_fn

        if config_store is None or worker_queues is None or create_queue_fn is None:
            return

        new_max = config_store.get("process.max_workers")
        if not isinstance(new_max, (int, float, str)):
            return

        target_size = max(1, int(new_max) - self.manager._overhead_count)
        managed_ids = sorted(
            [wid for wid in worker_queues.keys() if wid.startswith("worker_")],
            key=lambda x: int(x.split("_")[-1]),
        )
        current_size = len(managed_ids)

        if target_size == current_size:
            return

        if target_size > current_size:
            for i in range(current_size, target_size):
                worker_id = f"worker_{i}"
                if worker_id not in worker_queues:
                    worker_queues[worker_id] = create_queue_fn()
                    ff_logging.log(
                        f"ProcessManager: scaled up, added {worker_id} "
                        f"(pool size {current_size} → {target_size})"
                    )
        else:
            workers_to_remove = managed_ids[target_size:]
            for worker_id in workers_to_remove:
                if worker_id in worker_queues:
                    try:
                        worker_queues[worker_id].put(None)
                    except Exception:
                        pass
                    del worker_queues[worker_id]
                    ff_logging.log(
                        f"ProcessManager: scaled down, removed {worker_id} "
                        f"(pool size {current_size} → {target_size})"
                    )

    def health_check_process(
        self, name: str, process_info: ProcessInfo, current_time: float
    ) -> bool:
        """Perform health check on a single process."""
        process_info.last_health_check = current_time

        if not process_info.is_alive() and process_info.state == ProcessState.RUNNING:
            ff_logging.log_failure(f"Process '{name}' died unexpectedly")
            process_info.state = ProcessState.FAILED

            if self.manager.process_config.auto_restart:
                return self.manager.restart_process(name)
            return False

        return True
