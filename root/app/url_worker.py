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
from subprocess import check_output, PIPE, STDOUT
from time import sleep

import calibre_info
import calibredb_utils
import config_models
import fanfic_info
import ff_logging
import notification_wrapper
import regex_parsing
import retry_types
import system_utils


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
    # Note: We could attach the decision to the fanfic object if needed
    waiting_queue.put(fanfic)


def get_path_or_url(
    ff_info: fanfic_info.FanficInfo,
    cdb_info: calibre_info.CalibreInfo,
    location: str = "",
) -> str:
    """
    Retrieves the path of an exported story from the Calibre library or the story's
    URL if not in Calibre.

    This function checks if the specified fanfic exists in the Calibre library. If
    it does, the function exports the story to a given location and returns the
    path to the exported file. If the story is not found in the Calibre library,
    the function returns the URL of the story instead.

    Args:
        ff_info (fanfic_info.FanficInfo): The fanfic information object containing
            details about the fanfic.
        cdb_info (calibre_info.CalibreInfo): The Calibre database information
            object for accessing the library.
        location (str, optional): The directory path where the story should be
            exported. Defaults to an empty string, which means the current
            directory.

    Returns:
        str: The path to the exported story file if it exists in Calibre, or the
            URL of the story otherwise.
    """
    # Check if the story exists in the Calibre library by attempting to retrieve its ID
    if ff_info.get_id_from_calibredb(cdb_info):
        # Export the story to the specified location and return the path to the exported file
        calibredb_utils.export_story(
            fanfic_info=ff_info, location=location, calibre_info=cdb_info
        )
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


def execute_command(command: str) -> str:
    """
    Executes a shell command and returns its output.

    Args:
        command (str): The command to execute.

    Returns:
        str: The output of the command.
    """
    ff_logging.log_debug(f"\tExecuting command: {command}")
    return check_output(command, shell=True, stderr=STDOUT, stdin=PIPE).decode("utf-8")


def process_fanfic_addition(
    fanfic: fanfic_info.FanficInfo,
    cdb: calibre_info.CalibreInfo,
    temp_dir: str,
    site: str,
    path_or_url: str,
    waiting_queue: mp.Queue,
    notification_info: notification_wrapper.NotificationWrapper,
    retry_config: config_models.RetryConfig,
) -> None:
    """
    Processes the addition of a fanfic to Calibre, updates the database, and sends
    a notification.

    This function integrates a fanfic into the Calibre library. It checks if the
    fanfic already exists in the library by its Calibre ID. If so, the existing
    entry is removed for the updated version. The fanfic is added to Calibre from
    a temporary directory. Upon successful addition, a notification is sent via
    Pushbullet. If the process fails, the failure is logged, and the fanfic is
    placed back into the waiting queue for another attempt.

    Args:
        fanfic (fanfic_info.FanficInfo): The fanfic information object, containing
            details like the URL and site.
        cdb (calibre_info.CalibreInfo): The Calibre database information object,
            used for adding or removing fanfics.
        temp_dir (str): The path to the temporary directory where the fanfic is
            downloaded.
        site (str): The name of the site from which the fanfic is being updated.
        path_or_url (str): The path or URL to the fanfic that is being updated.
        waiting_queue (mp.Queue): The multiprocessing queue where fanfics are
            placed if they need to be reprocessed.
        notification_info (notification_wrapper.NotificationWrapper): The object for sending notifications.

    Returns:
        None
    """
    if fanfic.calibre_id:
        # If the fanfic already has a Calibre ID, it means it's already in the Calibre database.
        # Log the intention to remove the existing story from Calibre before updating it.
        ff_logging.log(
            f"\t({site}) Going to remove story {fanfic.calibre_id} from Calibre.",
            "OKGREEN",
        )
        # Remove the existing story from Calibre using its Calibre ID.
        calibredb_utils.remove_story(fanfic_info=fanfic, calibre_info=cdb)
    # Add the updated story to Calibre. This involves adding the story from the temporary directory
    # where it was downloaded and processed.
    calibredb_utils.add_story(location=temp_dir, fanfic_info=fanfic, calibre_info=cdb)

    # After attempting to add the story to Calibre, check if the story's ID can be retrieved from Calibre.
    # This serves as a verification step to ensure the story was successfully added.
    if not fanfic.get_id_from_calibredb(cdb):
        # If the story's ID cannot be retrieved, log the failure and handle it accordingly.
        # This might involve sending a notification about the failure and possibly re-queuing the story for another attempt.
        ff_logging.log_failure(f"\t({site}) Failed to add {path_or_url} to Calibre")
        handle_failure(fanfic, notification_info, waiting_queue, retry_config, cdb)
    else:
        # If the story was successfully added to Calibre, send a notification about the new download.
        # This notification includes the story's title and the site it was downloaded from.
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

    Example:
        ```python
        # Normal update
        cmd = construct_fanficfare_command(calibre_info, fanfic, "story.epub")
        # Returns: 'python -m fanficfare.cli -u "story.epub" --update-cover --non-interactive'

        # Force update requested
        fanfic.behavior = "force"
        cmd = construct_fanficfare_command(calibre_info, fanfic, url)
        # Returns: 'python -m fanficfare.cli --force "url" --update-cover --non-interactive'
        ```

    Configuration Conflicts:
        When update_method is "update_no_force", any force requests are ignored
        and a normal update (-u) is performed instead. This allows administrators
        to disable force updates globally while maintaining normal update functionality.

    Note:
        The constructed command includes --non-interactive to prevent FanFicFare
        from prompting for user input, which is essential for automated operation.
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
        # Use force flag when explicitly requested or configured
        command += " --force"
    elif update_method == "update_always":
        # Always perform full refresh of all chapters
        command += " -U"
    else:  # Default to 'update' behavior
        # Normal update - only download new chapters
        command += " -u"

    # Add the target path/URL and standard options for automated operation
    command += f' "{path_or_url}" --update-cover --non-interactive'
    return command


def url_worker(
    queue: mp.Queue,
    cdb: calibre_info.CalibreInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    waiting_queue: mp.Queue,
    config_path: str,
) -> None:
    """
    Main worker function for processing fanfiction downloads in a dedicated process.

    This function implements the core download worker loop that processes FanficInfo
    objects from a queue, downloads or updates stories using FanFicFare, integrates
    them with Calibre libraries, and handles comprehensive error recovery with
    retry logic.

    Args:
        queue (mp.Queue): Input queue containing FanficInfo objects to process.
                         Worker continuously monitors this queue for new work.
        cdb (calibre_info.CalibreInfo): Calibre library configuration and connection
                                       information for story management.
        notification_info (notification_wrapper.NotificationWrapper): Notification
                                                                     system for sending success/failure alerts.
        waiting_queue (mp.Queue): Queue for stories that need to be retried later
                                 due to failures or timing issues.
        config_path (str): Path to the TOML configuration file for loading retry settings.

    Processing Flow:
        1. Monitor queue for new FanficInfo objects
        2. Determine if story exists in Calibre (update vs. new download)
        3. Create temporary workspace with configuration files
        4. Execute FanFicFare command with appropriate flags
        5. Parse output for success/failure/retry conditions
        6. Integrate successful downloads with Calibre library
        7. Handle failures with sophisticated retry logic
        8. Send appropriate notifications for completion status

    Error Handling:
        - Command execution failures: Logged and sent to failure handler
        - Regex parsing: Detects permanent vs. retryable failures
        - Force retry detection: Automatically retries with --force when appropriate
        - Calibre integration: Verifies successful addition to library

    Temporary Directory Management:
        Each processing attempt uses an isolated temporary directory that includes:
        - Downloaded story files from FanFicFare
        - Calibre configuration files (defaults.ini, personal.ini)
        - Automatic cleanup regardless of success/failure

    Example Usage:
        ```python
        # Typically run in separate process via ProcessManager
        import multiprocessing as mp

        work_queue = mp.Queue()
        retry_queue = mp.Queue()
        calibre_config = CalibreInfo("/path/to/library")
        notifier = NotificationWrapper(config)

        # This runs indefinitely until process termination
        url_worker(work_queue, calibre_config, notifier, retry_queue)
        ```

    Infinite Loop:
        This function runs indefinitely and should be executed in a separate
        process. It only exits when the process is terminated externally or
        the queue receives a None sentinel value.

    Thread Safety:
        Designed for multiprocessing environments. Each worker operates in
        isolation with its own temporary workspace and Calibre connection.
        All inter-process communication occurs through thread-safe queues.

    Configuration Awareness:
        Respects all Calibre and FanFicFare configuration options including:
        - update_method settings (update, update_always, force, update_no_force)
        - Calibre library paths (local or server-based)
        - Force request handling and conflicts
        - Notification preferences

    Note:
        Workers sleep for 5 seconds when the queue is empty to reduce CPU
        usage while maintaining reasonable responsiveness to new work.
    """
    # Load retry configuration from TOML file
    retry_config = None
    try:
        config = config_models.ConfigManager.load_config(config_path)
        retry_config = config.retry
    except (config_models.ConfigError, config_models.ConfigValidationError) as e:
        ff_logging.log_failure(f"Failed to load retry configuration: {e}")

    # Use default configuration if loading failed
    if retry_config is None:
        retry_config = config_models.RetryConfig()

    while True:
        # Check for available work, sleep briefly if queue is empty
        if queue.empty():
            sleep(5)
            continue

        # Retrieve next fanfiction to process
        fanfic = queue.get()
        # Skip None sentinel values used for graceful shutdown
        if fanfic is None:
            continue

        # Process fanfiction in isolated temporary workspace
        with system_utils.temporary_directory() as temp_dir:
            site = fanfic.site
            ff_logging.log(f"({site}) Processing {fanfic.url}", "HEADER")

            # Determine if this is an update (existing file) or new download (URL)
            path_or_url = get_path_or_url(fanfic, cdb, temp_dir)
            ff_logging.log(f"\t({site}) Updating {path_or_url}", "OKGREEN")

            # Build FanFicFare command based on configuration and fanfic state
            base_command = construct_fanficfare_command(cdb, fanfic, path_or_url)
            # Execute command in temporary directory context
            command = f"cd {temp_dir} && {base_command}"

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
                output = execute_command(command)

            except Exception as e:
                # Log execution failure and route to failure handler
                ff_logging.log_failure(
                    f"\t({site}) Failed to update {path_or_url}: {e}"
                )
                handle_failure(
                    fanfic, notification_info, waiting_queue, retry_config, cdb
                )
                continue

            # Parse FanFicFare output for permanent failure conditions
            if not regex_parsing.check_failure_regexes(output):
                handle_failure(
                    fanfic, notification_info, waiting_queue, retry_config, cdb
                )
                continue

            # Check for conditions that can be resolved with force retry
            if regex_parsing.check_forceable_regexes(output):
                # Set force behavior and re-queue for immediate retry
                fanfic.behavior = "force"
                queue.put(fanfic)
                continue

            # Process successful download - integrate with Calibre library
            process_fanfic_addition(
                fanfic,
                cdb,
                temp_dir,
                site,
                path_or_url,
                waiting_queue,
                notification_info,
                retry_config,
            )
