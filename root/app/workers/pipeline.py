"""
Main pipeline logic for URL worker processes.
"""

import multiprocessing as mp
import subprocess
import time

from utils import ff_logging
from calibre_integration import calibredb_utils
from models import config_models
from notifications import notification_wrapper
from utils import system_utils
from models import fanfic_info
from parsers import regex_parsing

# Import from sibling modules
from . import common
from . import command
from . import handlers


def _process_task(
    fanfic: fanfic_info.FanficInfo,
    calibre_client: calibredb_utils.CalibreDBClient,
    notification_info: notification_wrapper.NotificationWrapper,
    ingress_queue: mp.Queue,
    retry_config: config_models.RetryConfig,
    worker_id: str,
) -> bool:
    """
    Process a single fanfiction task.

    Returns:
        bool: True if the URL should be removed from active_urls, False otherwise.
    """
    site = fanfic.site

    # Create temporary directory for processing
    with system_utils.temporary_directory() as temp_dir:
        ff_logging.log(f"({site}) Processing {fanfic.url}", "HEADER")

        # 1. Determine target path or URL
        path_or_url = common.get_path_or_url(fanfic, calibre_client)

        # Extract title from epub filename if we're updating an existing story
        if path_or_url.endswith(".epub"):
            extracted_title = common.extract_title_from_epub_path(path_or_url)
            if extracted_title != path_or_url:  # Only update if extraction succeeded
                fanfic.title = extracted_title
                ff_logging.log_debug(
                    f"\t({site}) Extracted title from filename: {fanfic.title}"
                )

            # Log epub metadata for debugging
            if ff_logging.is_verbose():
                common.log_epub_metadata(path_or_url, site)

        # 2. Construct FanFicFare command
        ff_logging.log(f"\t({site}) Updating {path_or_url}", "OKGREEN")
        try:
            cmd_args = command.construct_fanficfare_command(
                calibre_client.cdb_info, fanfic, path_or_url
            )
        except Exception as e:
            ff_logging.log_failure(f"({site}) Failed to construct command: {e}")
            handlers.handle_failure(
                fanfic,
                notification_info,
                ingress_queue,
                retry_config,
                calibre_client.cdb_info,
            )
            return handlers.check_active_removal(fanfic)

        # 3. Execute FanFicFare command
        try:
            # Handle special case: force requested but update_no_force configured
            if (
                fanfic.behavior == "force"
                and calibre_client.cdb_info.update_method == "update_no_force"
            ):
                # Force failure to trigger special notification via failure handler
                raise Exception(
                    "Force update requested but update method is 'update_no_force'"
                )

            # Set up temporary workspace with configuration files
            calibre_client.cdb_info.copy_configs_to_temp_dir(temp_dir)

            # Run command in temp_dir
            output = command.execute_command(cmd_args, cwd=temp_dir)
            ff_logging.log_debug(
                f"\t({site}) FanFicFare output preview: {output[:100]}..."
            )

        except (subprocess.CalledProcessError, Exception) as e:
            # Handle execution failure
            error_msg = str(e)

            ff_logging.log_failure(
                f"\t({site}) Failed to update {path_or_url}: {error_msg}"
            )

            # Log detailed output if available
            if hasattr(e, "output") and e.output:
                error_output = e.output
                if isinstance(error_output, bytes):
                    error_output = error_output.decode("utf-8", errors="replace")
                ff_logging.log_debug(f"\t({site}) FanFicFare output:\n{error_output}")

            if hasattr(e, "stderr") and e.stderr:
                error_stderr = e.stderr
                if isinstance(error_stderr, bytes):
                    error_stderr = error_stderr.decode("utf-8", errors="replace")
                ff_logging.log_debug(f"\t({site}) FanFicFare STDERR:\n{error_stderr}")

            handlers.handle_failure(
                fanfic,
                notification_info,
                ingress_queue,
                retry_config,
                calibre_client.cdb_info,
            )
            return handlers.check_active_removal(fanfic)

        # 4. Check outputs for permanent failure indications
        if not regex_parsing.check_failure_regexes(output):
            handlers.handle_failure(
                fanfic,
                notification_info,
                ingress_queue,
                retry_config,
                calibre_client.cdb_info,
            )
            return handlers.check_active_removal(fanfic)

        # Check for conditions that can be resolved with force retry
        if regex_parsing.check_forceable_regexes(output):
            # Set force behavior and re-queue for immediate retry
            fanfic.behavior = "force"
            ingress_queue.put(fanfic)
            return False  # Don't remove from active urls as we are re-queueing

        # 5. Integrate with Calibre (Process Addition)
        handlers.process_fanfic_addition(
            fanfic,
            calibre_client,
            temp_dir,
            site,
            path_or_url,
            ingress_queue,  # Passing ingress/waiting queue for retries
            notification_info,
            retry_config,
        )

        return True  # Success, remove from active


def url_worker(
    queue: mp.Queue,
    calibre_client: calibredb_utils.CalibreDBClient,
    notification_info: notification_wrapper.NotificationWrapper,
    waiting_queue: mp.Queue,
    retry_config: config_models.RetryConfig,
    worker_id: str,
    active_urls: dict | None = None,
    verbose: bool = False,
) -> None:
    """
    Main worker function for processing fanfiction downloads in a dedicated process.
    """
    # Initialize logging for this process
    ff_logging.set_verbose(verbose)

    ff_logging.log_debug(f"Starting Worker {worker_id}")

    # Track last site to release lock
    last_finished_site = None

    while True:
        try:
            # Signal idle if we finished a site
            if last_finished_site:
                # We need to signal coordinator.
                # But worker queues are one-way usually?
                # The architecture implies we communicate back?
                # Original coordinator had "ingress_queue" which workers put signals into?
                # Wait, where is ingress_queue?
                # In original url_worker, it used `queue` to GET tasks.
                # Does it PUT to `queue`? No.
                # Coordinator manages assignments.
                # Ah, `waiting_queue` in arguments. Is that the ingress queue?
                # In `fanficdownload.py`:
                # `ingress_queue = mp.Queue()`
                # `pm.register_process(..., args=(worker_queues[name], cdb_info, notification_wrapper, ingress_queue, ...))`
                # So `waiting_queue` param IS the `ingress_queue` of Coordinator!
                # Yes, because `handle_failure` puts retries there.

                # Signal IDLE
                # We put ('WORKER_IDLE', worker_id, last_finished_site) into ingress_queue
                waiting_queue.put(("WORKER_IDLE", worker_id, last_finished_site))
                last_finished_site = None

            # Blocking get - wait for work
            try:
                fanfic = queue.get()

                # Check for Poison Pill (None)
                if fanfic is None:
                    ff_logging.log(f"Worker {worker_id} stopping", "HEADER")
                    break

            except Exception as e:
                if isinstance(e, ValueError):  # Queue closed
                    ff_logging.log(f"Worker {worker_id} queue closed", "WARNING")
                    break
                ff_logging.log_failure(f"Worker {worker_id} error waiting: {e}")
                time.sleep(1)
                continue

            # Process Task
            should_remove = True
            try:
                should_remove = _process_task(
                    fanfic,
                    calibre_client,
                    notification_info,
                    waiting_queue,  # passed as ingress_queue
                    retry_config,
                    worker_id,
                )
            except Exception as e:
                ff_logging.log_failure(
                    f"Worker {worker_id} crashed on task {fanfic.url}: {e}"
                )
            finally:
                last_finished_site = fanfic.site

                # Update active_urls
                if active_urls is not None and should_remove:
                    try:
                        if fanfic.url in active_urls:
                            del active_urls[fanfic.url]
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
