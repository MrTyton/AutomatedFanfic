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

import time
from queue import Empty

from utils import ff_logging
from models import active_urls as active_urls_utils
from models.context import WorkerContext
from models.queue_types import IngressQueue, WorkerQueue
from utils import system_utils
from models import fanfic_info

# Import from sibling modules
from . import common
from . import command
from . import handlers


def _signal_worker_idle(
    ingress_queue: IngressQueue,
    worker_id: str,
    current_site: str | None,
    *,
    suppress_errors: bool = True,
) -> None:
    """Signal WORKER_IDLE to the coordinator if the worker was holding a site lock."""
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
    """
    Process a single fanfiction task.

    Returns:
        bool: True if the URL should be removed from active_urls, False otherwise.
    """
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

        # 2. Handle special case: force requested but update_no_force configured
        action = "Downloading" if path_or_url == fanfic.url else "Updating"
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
            return handlers.check_active_removal(fanfic)

        # 3. Execute FanFicFare via direct Python API
        fff_result = command.execute_fanficfare_direct(
            calibre_client.cdb_info, fanfic, path_or_url, temp_dir
        )

        # 4. Evaluate result
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

        # 5. Integrate with Calibre (Process Addition)
        result = handlers.process_fanfic_addition(
            fanfic,
            ctx,
            temp_dir,
            path_or_url,
        )

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
) -> None:
    """
    Main worker function for processing fanfiction downloads in a dedicated process/thread.
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

    # Track current site being processed
    current_site: str | None = None

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
                # Continue waiting for more work
                continue
            except Exception as e:
                if isinstance(e, ValueError):  # Queue closed
                    _signal_worker_idle(ingress_queue, worker_id, current_site)
                    current_site = None
                    ff_logging.log(f"Worker {worker_id} queue closed", "WARNING")
                    break
                ff_logging.log_failure(f"Worker {worker_id} error waiting: {e}")
                time.sleep(1)
                continue

            # Track which site we're processing
            current_site = fanfic.site
            ff_logging.set_thread_site(fanfic.site)

            # Mark as actively being processed by this worker thread
            active_urls_utils.mark_url_processing(
                active_urls, fanfic.url, site=fanfic.site
            )

            # Process Task
            should_remove = True
            try:
                should_remove = _process_task(fanfic, ctx)
            except Exception as e:
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
                                active_urls[fanfic.url] = existing
                    except Exception as e:
                        ff_logging.log_failure(
                            f"Worker {worker_id} failed to update active_urls: {e}"
                        )

        except KeyboardInterrupt:
            ff_logging.log(f"Worker {worker_id} interrupted", "WARNING")
            break
        except Exception as e:
            ff_logging.log_failure(f"Worker {worker_id} critical error: {e}")
            time.sleep(5)
