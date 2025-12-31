"""
Fanfiction Download Worker Processes for AutomatedFanfic

This module implements the core fanfiction download and processing logic for the
AutomatedFanfic application. It manages worker processes that consume URLs from
queues, download fanfiction using FanFicFare, integrate with Calibre libraries,
and handle retry logic with exponential backoff.

Key Features:
    - Multiprocessing worker pools for concurrent fanfiction downloads
    - FanFicFare CLI integration with dynamic command construction
    - Calibre library integration for story management
    - Sophisticated retry logic with exponential backoff and "Hail-Mary" attempts
    - Temporary directory management for safe file operations
    - Comprehensive error detection and handling
    - Notification system integration for success/failure reporting

Architecture:
    Workers operate in separate processes, consuming FanficInfo objects from
    multiprocessing queues. Each worker manages its own temporary workspace
    and Calibre interactions, with sophisticated error handling and retry
    mechanisms to handle various failure scenarios.

Processing Flow:
    1. Worker retrieves FanficInfo from assigned queue
    2. Determines if story exists in Calibre (update vs. new download)
    3. Constructs appropriate FanFicFare command based on configuration
    4. Downloads/updates story in temporary directory with config files
    5. Parses FanFicFare output for success/failure/retry conditions
    6. Integrates successful downloads with Calibre library
    7. Sends notifications and handles retry logic for failures

Retry Logic:
    The module implements sophisticated retry handling:
    - Exponential backoff: 1min, 2min, 3min, ..., up to 11 attempts
    - Force retry detection: Automatically detects conditions requiring --force
    - Hail-Mary protocol: Final attempt after 12-hour delay
    - Configuration-aware: Respects update_no_force settings

Example:
    ```python
    import multiprocessing as mp
    from url_worker import url_worker
    from calibre_info import CalibreInfo

    # Set up worker process
    queue = mp.Queue()
    calibre_info = CalibreInfo("/path/to/library")
    notification_wrapper = NotificationWrapper(config)
    waiting_queue = mp.Queue()

    # Start worker (typically in separate process)
    url_worker(queue, calibre_info, notification_wrapper, waiting_queue)
    ```

Configuration Integration:
    Workers respect various configuration options:
    - update_method: Controls FanFicFare command flags (-u, -U, --force)
    - update_no_force: Overrides force requests for specific behavior
    - Calibre paths: Both local and server-based libraries supported
    - Notification settings: Success/failure reporting configuration

Dependencies:
    - fanficfare: CLI tool for downloading fanfiction
    - calibre: Library management and book format conversion
    - multiprocessing: Queue-based worker coordination
    - Various internal modules for configuration, logging, and utilities

Thread Safety:
    All functions are designed for multiprocessing environments with
    proper queue-based communication and isolated temporary workspaces
    for each worker process.
"""

import multiprocessing as mp
from queue import Empty
from subprocess import CalledProcessError, check_output, PIPE, STDOUT

import calibre_info
import calibredb_utils
import config_models
from config_models import MetadataPreservationMode
import fanfic_info
import ff_logging
import notification_wrapper
import regex_parsing
import retry_types
import system_utils
import zipfile
from xml.etree import ElementTree as ET

import update_strategies


def get_fanficfare_version() -> str:
    """Get the FanFicFare version by running python -m fanficfare.cli --version.

    Returns:
        str: FanFicFare version string or error message if unavailable.
    """
    try:
        command = "python -m fanficfare.cli --version"
        output = execute_command(command)

        # Output format is typically "Version: X.X.X"
        output = output.strip()

        # Extract just the version number if possible
        import re

        version_match = re.search(r"Version:\s*(\d+\.\d+\.\d+)", output)
        if version_match:
            return version_match.group(1)
        return output  # Return full output if pattern not found

    except Exception as e:
        return f"Error: {e}"


def handle_failure(
    fanfic: fanfic_info.FanficInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    waiting_queue: mp.Queue,
    retry_config: config_models.RetryConfig,
    cdb: calibre_info.CalibreInfo | None = None,
) -> None:
    """
    Handle fanfiction download failures using comprehensive retry decision logic.

    This function processes failed downloads by incrementing the failure count
    and determining the complete retry strategy including timing, notifications,
    and routing. Uses the centralized retry decision logic to eliminate redundancy.

    Args:
        fanfic (fanfic_info.FanficInfo): The fanfiction object that failed to process.
        notification_info (notification_wrapper.NotificationWrapper): Notification
                                                                     system for sending failure alerts.
        waiting_queue (mp.Queue): Queue for stories that need delayed retry
        retry_config (config_models.RetryConfig): Retry configuration settings
        cdb (calibre_info.CalibreInfo, optional): Calibre configuration for checking
                                                 update method compatibility with force requests.

    Note:
        This function makes the complete retry decision and handles all aspects
        including notifications, logging, and routing to appropriate queues.
    """
    fanfic.increment_repeat()

    # Check for special case: force requested but update_no_force configured
    is_force_with_update_no_force = bool(
        cdb and fanfic.behavior == "force" and cdb.update_method == "update_no_force"
    )

    # Get comprehensive retry decision including timing and notifications
    retry_count = fanfic.repeats or 0
    decision = retry_types.determine_retry_decision(
        retry_count, retry_config, is_force_with_update_no_force
    )

    # Store the decision in the fanfic object for later use by ff_waiter
    fanfic.retry_decision = decision

    # Handle decision based on action
    if decision.action == retry_types.FailureAction.ABANDON:
        if decision.should_notify:
            notification_info.send_notification(
                "Fanfiction Update Permanently Skipped",
                f"Update for {fanfic.url} was permanently skipped because a force was requested but the update method is set to 'update_no_force'. The force request was ignored and a normal update was attempted instead.",
                fanfic.site,
            )

        ff_logging.log_failure(
            f"Maximum retries reached for {fanfic.title}. "
            f"Abandoning after {fanfic.repeats} attempts."
        )
        return

    # Handle RETRY and HAIL_MARY cases
    if decision.action == retry_types.FailureAction.HAIL_MARY:
        ff_logging.log_failure(
            f"Maximum attempts reached for {fanfic.url}. Activating Hail-Mary Protocol."
        )

        if decision.should_notify:
            notification_info.send_notification(
                f"Fanfiction Download Failed, trying Hail-Mary in {decision.delay_minutes / 60:.2f} hours.",
                fanfic.url,
                fanfic.site,
            )

    ff_logging.log_failure(
        f"Sending {fanfic.title} to waiting queue for {decision.action.value}. "
        f"Attempt {fanfic.repeats}"
    )

    # Send to waiting queue with decision information attached
    # Note: Decision could be attached to the fanfic object if needed
    waiting_queue.put(fanfic)


def get_path_or_url(
    ff_info: fanfic_info.FanficInfo,
    calibre_client: calibredb_utils.CalibreDBClient,
    location: str = "",
) -> str:
    """
    Retrieves the path of an exported story from the Calibre library or the story's
    URL if not in Calibre.

    Args:
        ff_info (fanfic_info.FanficInfo): The fanfic information object.
        calibre_client (calibredb_utils.CalibreDBClient): The Calibre DB client.
        location (str, optional): The directory path to export to.

    Returns:
        str: The path to the exported story file if it exists in Calibre, or the
            URL of the story otherwise.
    """
    # Check if the story exists in the Calibre library by attempting to retrieve its ID
    if calibre_client.get_story_id(ff_info):
        # Export the story to the specified location
        calibre_client.export_story(fanfic=ff_info, location=location)
        # Assuming export_story function successfully exports the story, retrieve and return the path to the exported file
        exported_files = system_utils.get_files(
            location, file_extension=".epub", return_full_path=True
        )
        # Check if the list is not empty
        if exported_files:
            # Return the first file path found
            return exported_files[0]

    # If the story does not exist in the Calibre library or no files were exported, return the URL of the story
    return ff_info.url


def extract_title_from_epub_path(epub_path: str) -> str:
    """
    Extract the story title from an epub file path.

    Args:
        epub_path (str): Path to the epub file, which may contain the story title

    Returns:
        str: Extracted title, or the original path if extraction fails
    """
    import os

    try:
        # Get the filename without directory path
        # Handle both Windows (\) and Unix (/) path separators
        filename = os.path.basename(epub_path.replace("\\", "/"))

        # Remove the .epub extension
        if filename.lower().endswith(".epub"):
            title = filename[:-5]  # Remove last 5 characters (.epub)
            return title
    except Exception:
        # If extraction fails, return the original path
        pass

    return epub_path


def log_epub_metadata(epub_path: str, site: str) -> None:
    """
    Read and log the metadata from an epub file to help diagnose FanFicFare issues.

    This function extracts key metadata fields from the epub that FanFicFare uses
    to determine the source URL and other story details. This is crucial for
    debugging cases where FanFicFare can't find the source URL.

    Args:
        epub_path (str): Path to the epub file
        site (str): Site identifier for logging context
    """
    if not ff_logging.verbose.value:
        return

    try:
        ff_logging.log_debug(f"\t({site}) Reading epub metadata from: {epub_path}")

        with zipfile.ZipFile(epub_path, "r") as epub:
            # Find the .opf file which contains all metadata
            opf_path = next(
                (name for name in epub.namelist() if name.endswith(".opf")), None
            )

            if not opf_path:
                ff_logging.log_debug(f"\t({site}) Could not find .opf file in epub")
                return

            opf_content = epub.read(opf_path).decode("utf-8")
            root = ET.fromstring(opf_content)

            # Find metadata section (handle namespace)
            metadata = root.find(".//{http://www.idpf.org/2007/opf}metadata")
            if metadata is None:
                ff_logging.log_debug(
                    f"\t({site}) No metadata section found in .opf file"
                )
                return

            ff_logging.log_debug(f"\t({site}) === EPUB METADATA ===")

            # Log all metadata elements
            for elem in metadata:
                tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                text = elem.text or ""
                attribs = " ".join([f'{k}="{v}"' for k, v in elem.attrib.items()])

                if attribs:
                    ff_logging.log_debug(f"\t({site})   {tag_name} [{attribs}]: {text}")
                else:
                    ff_logging.log_debug(f"\t({site})   {tag_name}: {text}")

            ff_logging.log_debug(f"\t({site}) === END METADATA ===")

    except Exception as e:
        ff_logging.log_debug(f"\t({site}) Error reading epub metadata: {e}")


def execute_command(command: str, cwd: str | None = None) -> str:
    """
    Executes a shell command and returns its output.

    Args:
        command (str): The command to execute.
        cwd (str, optional): The directory to execute the command in.

    Returns:
        str: The output of the command.
    """
    debug_msg = f"\tExecuting command: {command}"
    if cwd:
        debug_msg += f" (in {cwd})"
    ff_logging.log_debug(debug_msg)
    return check_output(command, shell=True, stderr=STDOUT, stdin=PIPE, cwd=cwd).decode(
        "utf-8"
    )


def process_fanfic_addition(
    fanfic: fanfic_info.FanficInfo,
    calibre_client: calibredb_utils.CalibreDBClient,
    temp_dir: str,
    site: str,
    path_or_url: str,
    waiting_queue: mp.Queue,
    notification_info: notification_wrapper.NotificationWrapper,
    retry_config: config_models.RetryConfig,
) -> None:
    """
    Integrate downloaded fanfic with Calibre library.

    Args:
        fanfic: Fanfiction info
        calibre_client: CalibreDB client
        temp_dir: Temporary directory path
        site: Site identifier
        path_or_url: Path or URL being processed
        waiting_queue: Retry queue
        notification_info: Notification wrapper
        retry_config: Retry configuration
    """
    # Check if story exists in Calibre (update) or is new
    if calibre_client.get_story_id(fanfic):
        ff_logging.log(
            f"\t({site}) Fanfic is in Calibre with Story ID: {fanfic.calibre_id}",
            "OKBLUE",
        )

        # It's an update - check preservation mode
        preservation_mode = calibre_client.cdb_info.metadata_preservation_mode
        ff_logging.log_debug(
            f"\t({site}) Metadata preservation mode: {preservation_mode}"
        )

        # Dispatch to appropriate handler based on preservation mode
        if preservation_mode in (
            MetadataPreservationMode.ADD_FORMAT,
            "add_format",
        ):
            strategy = update_strategies.AddFormatStrategy()
        elif preservation_mode in (
            MetadataPreservationMode.PRESERVE_METADATA,
            "preserve_metadata",
        ):
            strategy = update_strategies.PreserveMetadataStrategy()
        else:  # MetadataPreservationMode.REMOVE_ADD or "remove_add"
            strategy = update_strategies.RemoveAddStrategy()

        success = strategy.execute(
            fanfic,
            calibre_client,
            temp_dir,
            site,
            path_or_url,
            waiting_queue,
            notification_info,
            retry_config,
            failure_handler=handle_failure,
        )

        if not success:
            return

    else:
        # New story - just add it
        calibre_client.add_story(location=temp_dir, fanfic=fanfic)

        # Verify addition
        if not calibre_client.get_story_id(fanfic):
            ff_logging.log_failure(f"\t({site}) Failed to add {path_or_url} to Calibre")
            handle_failure(
                fanfic,
                notification_info,
                waiting_queue,
                retry_config,
                calibre_client.cdb_info,
            )
            return

    # If we got here, everything succeeded
    ff_logging.log(f"\t({site}) Successfully processed {fanfic.title}", "OKGREEN")

    # Success - send notification
    notification_info.send_notification(
        "New Fanfiction Download", fanfic.title or "Unknown Title", site
    )


def construct_fanficfare_command(
    cdb: calibre_info.CalibreInfo,
    fanfic: fanfic_info.FanficInfo,
    path_or_url: str,
) -> str:
    """
    Construct the appropriate FanFicFare CLI command based on configuration and fanfic state.

    This function builds the FanFicFare command string dynamically based on the
    Calibre configuration's update method and the fanfiction's requested behavior.
    It handles various update strategies and configuration conflicts.

    Args:
        cdb (calibre_info.CalibreInfo): Calibre configuration containing the update_method
                                       setting that controls how updates are performed.
        fanfic (fanfic_info.FanficInfo): Fanfiction object that may have specific
                                        behavior requests (e.g., "force" for forced updates).
        path_or_url (str): The file path or URL that FanFicFare should process.

    Returns:
        str: Complete FanFicFare command string ready for execution.

    Update Method Behavior:
        - "update": Uses -u flag, respects force requests
        - "update_always": Always uses -U flag for full refresh
        - "force": Always uses --force flag
        - "update_no_force": Uses -u flag, IGNORES all force requests

    Command Flags:
        - -u: Normal update, only downloads new chapters
        - -U: Update always, re-downloads all chapters
        - --force: Force update, bypasses most checks and restrictions
        - --update-cover: Updates book cover art
        - --non-interactive: Prevents interactive prompts
        - --debug: Enable FanFicFare debug output (when verbose logging enabled)

    Example:
        ```python
        # Normal update
        cmd = construct_fanficfare_command(calibre_info, fanfic, "story.epub")
        # Returns: 'python -m fanficfare.cli -u "story.epub" --update-cover --non-interactive'

        # Force update requested
        fanfic.behavior = "force"
        cmd = construct_fanficfare_command(calibre_info, fanfic, url)
        # Returns: 'python -m fanficfare.cli -u --force "url" --update-cover --non-interactive'

        # With verbose logging enabled
        ff_logging.set_verbose(True)
        cmd = construct_fanficfare_command(calibre_info, fanfic, url)
        # Returns: 'python -m fanficfare.cli -u "url" --update-cover --non-interactive --debug'
        ```

    Configuration Conflicts:
        When update_method is "update_no_force", any force requests are ignored
        and a normal update (-u) is performed instead. This allows administrators
        to disable force updates globally while maintaining normal update functionality.

    Note:
        The constructed command includes --non-interactive to prevent FanFicFare
        from prompting for user input, which is essential for automated operation.
        When verbose logging is enabled globally, --debug is added to get detailed
        FanFicFare diagnostic output.
    """
    update_method = cdb.update_method
    command = "python -m fanficfare.cli"

    # Check if fanfiction specifically requests force behavior
    force_requested = fanfic.behavior == "force"

    # Determine appropriate update flag based on configuration and request
    if update_method == "update_no_force":
        # Special case: ignore all force requests and always use normal update
        command += " -u"
    elif force_requested or update_method == "force":
        # Use force flag WITH update flag (force is a modifier, not a replacement)
        command += " -u --force"
    elif update_method == "update_always":
        # Always perform full refresh of all chapters
        command += " -U"
    else:  # Default to 'update' behavior
        # Normal update - only download new chapters
        command += " -u"

    # Add the target path/URL and standard options for automated operation
    command += f' "{path_or_url}" --update-cover --non-interactive'

    # Add debug flag when verbose logging is enabled
    if ff_logging.verbose.value:
        command += " --debug"

    return command


def url_worker(
    queue: mp.Queue,
    calibre_client: calibredb_utils.CalibreDBClient,
    notification_info: notification_wrapper.NotificationWrapper,
    ingress_queue: mp.Queue,
    retry_config: config_models.RetryConfig,
    worker_id: str,
    active_urls: dict | None = None,
) -> None:
    """
    Main worker function for processing fanfiction downloads in a dedicated process.

    This function implements the consumers worker loop that requests tasks from
    the central coordinator, downloads/updates stories using FanFicFare, and
    handling Calibre integration.

    Args:
        queue (mp.Queue): Worker-specific input queue to receive tasks from Coordinator.
        calibre_client (calibredb_utils.CalibreDBClient): CalibreDB client instance.
        notification_info (notification_wrapper.NotificationWrapper): Notification system.
        ingress_queue (mp.Queue): Ingress queue to send retries back to Coordinator.
        retry_config (config_models.RetryConfig): Retry settings.
        worker_id (str): Unique identifier for this worker process.
        active_urls (dict, optional): Shared dictionary tracking active URLs.
    """
    cdb = calibre_client.cdb_info
    ff_logging.log(f"Starting Worker {worker_id}", "HEADER")

    # Track the last site processed to unlock it in the next request
    last_finished_site = None

    while True:
        try:
            # Try to get work immediately
            fanfic = queue.get_nowait()
        except Empty:
            # Queue is empty: Signal IDLE and block for new work
            ingress_queue.put(("WORKER_IDLE", worker_id, last_finished_site))
            last_finished_site = None  # Reset after sending signal
            try:
                fanfic = queue.get()  # Blocking wait
            except Exception as e:
                ff_logging.log_failure(
                    f"Worker {worker_id} error waiting for new work: {e}"
                )
                break
        except Exception as e:
            ff_logging.log_failure(f"Worker {worker_id} error getting from queue: {e}")
            break

        # Check for shutdown signal
        if fanfic is None:
            ff_logging.log(f"Worker {worker_id} received shutdown signal", "HEADER")
            break

        # We have a valid task
        should_remove_from_active = True
        site = fanfic.site
        path_or_url = fanfic.url

        # Mark site as current context for this worker (though we rely on coordinator for locking)
        try:
            with system_utils.temporary_directory() as temp_dir:
                ff_logging.log(f"({site}) Processing {fanfic.url}", "HEADER")

                # Determine if this is an update (existing file) or new download (URL)
                path_or_url = get_path_or_url(fanfic, calibre_client, temp_dir)

                # Extract title from epub filename if we're updating an existing story
                if path_or_url.endswith(".epub"):
                    extracted_title = extract_title_from_epub_path(path_or_url)
                    if (
                        extracted_title != path_or_url
                    ):  # Only update if extraction succeeded
                        fanfic.title = extracted_title
                        ff_logging.log_debug(
                            f"\t({site}) Extracted title from filename: {fanfic.title}"
                        )
                        # Also attempt to read full metadata for debugging
                        log_epub_metadata(path_or_url, site)

                ff_logging.log(f"\t({site}) Updating {path_or_url}", "OKGREEN")

                # Build FanFicFare command based on configuration and fanfic state
                base_command = construct_fanficfare_command(cdb, fanfic, path_or_url)

                try:
                    # Handle special case: force requested but update_no_force configured
                    if (
                        fanfic.behavior == "force"
                        and cdb.update_method == "update_no_force"
                    ):
                        # Force failure to trigger special notification via failure handler
                        raise Exception(
                            "Force update requested but update method is 'update_no_force'"
                        )

                    # Set up temporary workspace with configuration files
                    system_utils.copy_configs_to_temp_dir(cdb, temp_dir)

                    # Execute FanFicFare download/update command
                    output = execute_command(base_command, cwd=temp_dir)

                except CalledProcessError as e:
                    # Log execution failure with detailed output for debugging
                    ff_logging.log_failure(
                        f"\t({site}) Failed to update {path_or_url}: {e}"
                    )

                    # In verbose mode, show the actual FanFicFare output for debugging
                    if e.output:
                        error_output = (
                            e.output.decode("utf-8")
                            if isinstance(e.output, bytes)
                            else str(e.output)
                        )
                        ff_logging.log_debug(
                            f"\t({site}) FanFicFare output:\n{error_output}"
                        )

                    handle_failure(
                        fanfic, notification_info, ingress_queue, retry_config, cdb
                    )
                    continue
                except Exception as e:
                    # Log other execution failures
                    ff_logging.log_failure(
                        f"\t({site}) Failed to update {path_or_url}: {e}"
                    )
                    handle_failure(
                        fanfic, notification_info, ingress_queue, retry_config, cdb
                    )
                    continue

                # Parse FanFicFare output for permanent failure conditions
                if not regex_parsing.check_failure_regexes(output):
                    handle_failure(
                        fanfic, notification_info, ingress_queue, retry_config, cdb
                    )
                    continue

                # Check for conditions that can be resolved with force retry
                if regex_parsing.check_forceable_regexes(output):
                    # Set force behavior and re-queue for immediate retry
                    fanfic.behavior = "force"
                    ingress_queue.put(fanfic)
                    should_remove_from_active = False
                    continue

                # Process successful download - integrate with Calibre library

                process_fanfic_addition(
                    fanfic,
                    calibre_client,  # Passed instead of cdb
                    temp_dir,
                    site,
                    path_or_url,
                    ingress_queue,
                    notification_info,
                    retry_config,
                )
        finally:
            # Mark this site as finished for the next request
            last_finished_site = site

            # Cleanup active_urls
            if active_urls is not None and should_remove_from_active:
                # Check if it was retried (sent to waiting queue)
                if hasattr(fanfic, "retry_decision") and fanfic.retry_decision:
                    if (
                        fanfic.retry_decision.action
                        != retry_types.FailureAction.ABANDON
                    ):
                        # It's in waiting queue, keep it in active_urls
                        pass
                    else:
                        active_urls.pop(fanfic.url, None)
                else:
                    # Success or unhandled error (unlikely)
                    active_urls.pop(fanfic.url, None)
