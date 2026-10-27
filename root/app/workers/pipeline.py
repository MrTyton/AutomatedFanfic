"""
Main pipeline logic for URL worker processes.

Worker-Coordinator Communication:
    Workers communicate with the coordinator through two queues:
    1. ingress_queue: For WORKER_IDLE signals and force re-queues back to coordinator
    2. waiting_queue: For failed downloads needing exponential backoff via ff_waiter

    When a worker finishes processing all tasks for a site, it sends:
    ('WORKER_IDLE', worker_id, finished_site) to the ingress_queue.

    When a download fails and needs retry, it goes to the waiting_queue
    where ff_waiter applies exponential backoff before re-submitting.
"""

from queue import Empty
import threading
import time
from typing import cast

from models import active_urls as active_urls_utils
from models import fanfic_info
from models.active_urls import ActiveUrlEntry
from models.context import WorkerContext
from models.queue_types import IngressQueue, WorkerQueue
from utils import anubis_solver, ff_logging, system_utils

# Import from sibling modules
from . import command, common, cookie_cache, handlers

# Cooldown applied between a failed task and the next queued task on the same site,
# compensating for FanFicFare's SleepDecorator being bypassed when a request raises.
FAILURE_COOLDOWN_SECONDS: float = 5.0

_worker_local = threading.local()


def _signal_worker_idle(
    ingress_queue: IngressQueue,
    worker_id: str,
    current_site: str | None,
    *,
    suppress_errors: bool = True,
) -> None:
    """Signal WORKER_IDLE to the coordinator if the worker was holding a site lock.

    Args:
        ingress_queue (IngressQueue): Unified task ingress queue read by the coordinator.
        worker_id (str): Identifier of the worker releasing its site assignment.
        current_site (str | None): Site identifier whose lock is being released, or
            None if the worker is not currently assigned to a site.
        suppress_errors (bool, optional): Whether to swallow queue errors (e.g., during
            process shutdown). Defaults to True.
    """
    if current_site is None:
        return
    if suppress_errors:
        try:
            ingress_queue.put(("WORKER_IDLE", worker_id, current_site))
        except Exception:
            pass
    else:
        ingress_queue.put(("WORKER_IDLE", worker_id, current_site))
    ff_logging.set_thread_site(None)


def _process_task(
    fanfic: fanfic_info.FanficInfo,
    ctx: WorkerContext,
) -> bool:
    """Process a single fanfiction download or update task.

    Args:
        fanfic (FanficInfo): Fanfiction task metadata (URL, site, behavior, calibre_id).
        ctx (WorkerContext): Bundled worker dependencies (calibre_client, notification_info,
            ingress_queue, waiting_queue, retry_config, history_recorder, active_urls).

    Returns:
        bool: True if the URL should be removed from `active_urls` upon completion
            (succeeded or permanently abandoned), False if it remains active (waiting
            for retry or re-queued for force update).
    """
    _worker_local.last_task_failed = False
    site = fanfic.site
    calibre_client = ctx.calibre_client
    ingress_queue = ctx.ingress_queue
    history_recorder = ctx.history_recorder
    active_urls = ctx.active_urls

    # Create temporary directory for processing
    with system_utils.temporary_directory() as temp_dir:
        ff_logging.log_debug(f"({site}) Using temp directory: '{temp_dir}'")
        ff_logging.log(f"({site}) Processing {fanfic.url}")

        # 1. Determine target path or URL
        path_or_url = common.get_path_or_url(fanfic, calibre_client, location=temp_dir)

        # Extract title from epub filename if we're updating an existing story
        if path_or_url.endswith(".epub"):
            extracted_title = common.extract_title_from_epub_path(path_or_url)
            if extracted_title != path_or_url:  # Only update if extraction succeeded
                fanfic.title = extracted_title
                ff_logging.log_debug(
                    f"\t({site}) Extracted title from filename: {fanfic.title}"
                )
                # Push title to active_urls so the web UI can show it immediately.
                # Merge into the existing entry to preserve heap_gen and other fields.
                active_urls_utils.update_url_title(
                    active_urls,
                    fanfic.url,
                    title=fanfic.title,
                    site=fanfic.site,
                )
                # Update the pending history DB row with the title
                if history_recorder:
                    history_recorder.record_download_title_update(
                        url=fanfic.url, title=fanfic.title, site=fanfic.site
                    )

            # Log epub metadata for debugging
            if ff_logging.is_verbose():
                common.log_epub_metadata(path_or_url, site)

        is_new_story = path_or_url in (fanfic.url, fanfic.download_url)

        # 2. update_only mode: drop emailed URLs for stories not already in Calibre
        if is_new_story and fanfic.from_email and calibre_client.cdb_info.update_only:
            skip_message = (
                "Story not found in Calibre library and update_only is enabled"
            )
            ff_logging.log(f"\t({site}) Skipping {fanfic.url}: {skip_message}")
            if history_recorder:
                history_recorder.record_download_abandoned(
                    url=fanfic.url, error_message=skip_message, site=site
                )
            return True

        # 3. Handle special case: force requested but update_no_force configured
        action = "Downloading" if is_new_story else "Updating"
        ff_logging.log(f"\t({site}) {action} {path_or_url}")
        if (
            fanfic.behavior == "force"
            and calibre_client.cdb_info.update_method == "update_no_force"
        ):
            ff_logging.log_failure(
                f"({site}) Force update requested but update method is 'update_no_force'"
            )
            handlers.handle_failure(
                fanfic,
                ctx,
                error_message="Force update requested but update method is 'update_no_force'",
            )
            _worker_local.last_task_failed = True
            return handlers.check_active_removal(fanfic)

        # 4. Execute FanFicFare via direct Python API
        fff_result = command.execute_fanficfare_direct(
            calibre_client.cdb_info, fanfic, path_or_url, temp_dir
        )

        # Reactive Anubis check: if download failed, probe whether site serves an Anubis challenge
        if fff_result.has_failure and fff_result.target_url:
            cached_jar = cookie_cache.get_site_cookiejar(site)
            solved, updated_jar = anubis_solver.probe_and_solve_anubis(
                url=fff_result.target_url,
                user_agent=fff_result.effective_user_agent,
                cookiejar=cast(anubis_solver.LWPCookieJar | None, cached_jar),
            )
            if solved:
                ff_logging.log(
                    f"({site}) Anubis challenge solved on reactive probe. Retrying FanFicFare..."
                )
                anubis_solver.mark_site_anubis_protected(site)
                cookie_cache.set_site_cookiejar(site, updated_jar)
                fff_result = command.execute_fanficfare_direct(
                    calibre_client.cdb_info, fanfic, path_or_url, temp_dir
                )
                if not fff_result.has_failure:
                    ff_logging.log(
                        f"({site}) FanFicFare retry succeeded after Anubis resolution."
                    )

        # 5. Evaluate result
        if fff_result.has_failure:
            error_msg = (
                str(fff_result.exception)
                if fff_result.exception is not None
                else "; ".join(fff_result.failure_messages)
                or "FanFicFare reported a permanent failure condition."
            )
            ff_logging.log_failure(
                f"\t({site}) Failed to update {path_or_url}: {error_msg}"
            )
            handlers.handle_failure(
                fanfic,
                ctx,
                error_message=error_msg,
            )
            _worker_local.last_task_failed = True
            return handlers.check_active_removal(fanfic)

        if fff_result.is_forceable:
            # Conditions that can be resolved by force-retrying
            fanfic.behavior = "force"
            active_urls_utils.mark_url_queued(
                active_urls,
                fanfic.url,
                behavior="force",
                merge=True,
            )
            ingress_queue.put(fanfic)
            return False  # Keep in active_urls; re-queued for force retry

        # 6. Integrate with Calibre (Process Addition)
        result = handlers.process_fanfic_addition(
            fanfic,
            ctx,
            temp_dir,
            path_or_url,
        )
        if getattr(fanfic, "retry_decision", None) is not None:
            _worker_local.last_task_failed = True

        # If process_fanfic_addition was mocked in a test and returned None,
        # fall back to check_active_removal(fanfic).
        if result is None:
            return handlers.check_active_removal(fanfic)
        return bool(result)


def url_worker(
    queue: WorkerQueue,
    ctx: WorkerContext,
    worker_id: str,
    verbose: bool = False,
    idle_timeout: float | None = None,
) -> None:
    """Main worker loop for processing fanfiction downloads on a dedicated thread.

    Consumes `FanficInfo` tasks from `queue`, processes each via `_process_task`,
    updates `ctx.active_urls` and `ctx.history_recorder`, and signals `WORKER_IDLE`
    to `ctx.ingress_queue` when the worker's queue drains or on shutdown.

    Args:
        queue (WorkerQueue): Worker-specific task queue populated by the Coordinator.
        ctx (WorkerContext): Bundled worker dependencies and shared IPC state.
        worker_id (str): Unique identifier for this worker (e.g., 'worker_0').
        verbose (bool, optional): Enable verbose debug logging. Defaults to False.
        idle_timeout (float | None, optional): Maximum idle duration in seconds
            before terminating the worker thread. If None, the worker runs permanently.
            Defaults to None.
    """
    # Initialize logging for this process
    ff_logging.set_verbose(verbose)

    # Set unique color used for all logs in this thread
    try:
        # Extract ID number from "worker_12" -> 12
        w_index = int(worker_id.split("_")[-1])
    except ValueError, IndexError:
        w_index = 0

    worker_color = ff_logging.get_color_for_worker(w_index)
    ff_logging.set_thread_color(worker_color)

    ff_logging.log(f"Worker {worker_id} started")

    ingress_queue = ctx.ingress_queue
    active_urls = ctx.active_urls

    # Track current site being processed and whether its previous task failed
    current_site: str | None = None
    last_task_failed = False
    last_active_time = time.monotonic()

    while True:
        try:
            # Blocking get: short timeout when assigned a site to detect queue drain quickly,
            # longer timeout when already idle to avoid 100ms IPC polling against SyncManager.
            try:
                poll_timeout = 0.05 if current_site is not None else 2.0
                fanfic = queue.get(timeout=poll_timeout)

                # Check for Poison Pill (None)
                if fanfic is None:
                    _signal_worker_idle(ingress_queue, worker_id, current_site)
                    current_site = None
                    last_task_failed = False
                    ff_logging.log(f"Worker {worker_id} stopping", "HEADER")
                    break

            except Empty:
                # Queue is empty - signal idle if we were processing a site
                if current_site is not None:
                    finished_site = current_site
                    _signal_worker_idle(
                        ingress_queue,
                        worker_id,
                        finished_site,
                        suppress_errors=False,
                    )
                    ff_logging.log_debug(
                        f"Worker {worker_id} signaling idle after draining {finished_site} queue"
                    )
                    current_site = None
                    last_task_failed = False
                    system_utils.reclaim_memory()
                    last_active_time = time.monotonic()
                    continue

                if idle_timeout is not None and (
                    time.monotonic() - last_active_time >= idle_timeout
                ):
                    ff_logging.log_debug(
                        f"Worker {worker_id} reached idle timeout ({idle_timeout}s) - stopping thread"
                    )
                    try:
                        ingress_queue.put(("WORKER_STOPPED", worker_id, None))
                    except Exception as e:
                        ff_logging.log_debug(
                            f"Worker {worker_id} failed to signal stop to ingress queue: {e}"
                        )
                    system_utils.reclaim_memory()
                    break

                # Continue waiting for more work
                continue

            except Exception as e:
                if isinstance(e, ValueError):  # Queue closed
                    _signal_worker_idle(ingress_queue, worker_id, current_site)
                    current_site = None
                    last_task_failed = False
                    ff_logging.log(f"Worker {worker_id} queue closed", "WARNING")
                    break
                ff_logging.log_failure(f"Worker {worker_id} error waiting: {e}")
                time.sleep(1)
                continue

            # If the previous task on this site failed, FanFicFare's post-request
            # SleepDecorator was bypassed; cool down before hitting the site again.
            if last_task_failed and current_site == fanfic.site:
                ff_logging.log_debug(
                    f"({fanfic.site}) Cooling down {FAILURE_COOLDOWN_SECONDS}s after previous failure before next task"
                )
                time.sleep(FAILURE_COOLDOWN_SECONDS)

            # If the task was cancelled while queued, drop it immediately
            if active_urls is not None:
                try:
                    meta = dict(active_urls.get(fanfic.url, {}))
                    if meta.get("status") == "cancelled":
                        active_urls_utils.remove_active_url(active_urls, fanfic.url)
                        ff_logging.log(
                            f"Worker {worker_id}: Dropped cancelled task {fanfic.url}"
                        )
                        continue
                except Exception:
                    pass

            # Track which site we're processing
            current_site = fanfic.site
            ff_logging.set_thread_site(fanfic.site)

            # Mark as actively being processed by this worker thread
            if active_urls is not None:
                active_urls_utils.mark_url_processing(
                    active_urls, fanfic.url, site=fanfic.site
                )
            if ctx.history_recorder:
                ctx.history_recorder.record_download_processing(
                    fanfic.url, site=fanfic.site
                )

            # Process Task
            should_remove = True
            _worker_local.last_task_failed = False
            try:
                should_remove = _process_task(fanfic, ctx)
                last_task_failed = bool(
                    getattr(_worker_local, "last_task_failed", False)
                )
            except Exception as e:
                last_task_failed = True
                ff_logging.log_failure(
                    f"Worker {worker_id} crashed on task {fanfic.url}: {e}"
                )
                # Ensure we retry even on deep crashes
                handlers.handle_failure(
                    fanfic,
                    ctx,
                    error_message=str(e),
                )
                should_remove = handlers.check_active_removal(fanfic)
            finally:
                # Update active_urls
                if active_urls is not None:
                    try:
                        if should_remove:
                            if fanfic.url in active_urls:
                                del active_urls[fanfic.url]
                        elif getattr(fanfic, "retry_decision", None) is not None:
                            existing = dict(active_urls.get(fanfic.url, {}))
                            if existing.get("status") != "cancelled":
                                existing.setdefault("site", fanfic.site)
                                if getattr(fanfic, "title", None):
                                    existing["title"] = fanfic.title
                                if getattr(fanfic, "calibre_id", None):
                                    existing["calibre_id"] = fanfic.calibre_id
                                existing["status"] = "waiting"
                                active_urls[fanfic.url] = cast(ActiveUrlEntry, existing)
                    except Exception as e:
                        ff_logging.log_failure(
                            f"Worker {worker_id} failed to update active_urls: {e}"
                        )
                last_active_time = time.monotonic()

        except KeyboardInterrupt:
            ff_logging.log(f"Worker {worker_id} interrupted", "WARNING")
            break
        except Exception as e:
            ff_logging.log_failure(f"Worker {worker_id} critical error: {e}")
            time.sleep(5)
