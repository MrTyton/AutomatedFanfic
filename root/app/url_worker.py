import multiprocessing as mp
from subprocess import check_output, PIPE, STDOUT
from time import sleep

import calibre_info
import calibredb_utils
import fanfic_info
import ff_logging
import notification_wrapper
import regex_parsing
import system_utils


def handle_failure(
    fanfic: fanfic_info.FanficInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    queue: mp.Queue,
) -> None:
    """
    Manages the failure of fanfic processing by either logging and notifying the
    failure or re-queuing the fanfic for another attempt.

    This function checks if a fanfic has reached its maximum allowed attempts for
    processing. If it has, the function logs the failure and sends a notification
    about the failure. If the maximum attempts have not been reached, it increments
    the attempt counter for the fanfic and places it back into the processing queue
    for another attempt.

    Args:
        fanfic (fanfic_info.FanficInfo): The fanfic information object,
            encapsulating details about the fanfic.
        notification_info (notification_wrapper.NotificationWrapper): The object
            used for sending notifications via various services.
        queue (mp.Queue): The multiprocessing queue used for managing fanfics
            awaiting processing.

    Returns:
        None
    """
    # Check if the fanfic has exceeded the maximum number of processing attempts
    if fanfic.reached_maximum_repeats():
        # Log the failure and send a notification about this specific fanfic
        ff_logging.log_failure(
            f"Maximum attempts reached for {fanfic.url}. Skipping."
        )
        notification_info.send_notification(
            "Fanfiction Download Failed", fanfic.url, fanfic.site
        )
    else:
        # If not at maximum attempts, increment the attempt counter and re-queue the fanfic
        fanfic.increment_repeat()
        queue.put(fanfic)


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
    return check_output(command, shell=True, stderr=STDOUT, stdin=PIPE).decode(
        "utf-8"
    )


def process_fanfic_addition(
    fanfic: fanfic_info.FanficInfo,
    cdb: calibre_info.CalibreInfo,
    temp_dir: str,
    site: str,
    path_or_url: str,
    waiting_queue: mp.Queue,
    notification_info: notification_wrapper.NotificationWrapper,
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
    calibredb_utils.add_story(
        location=temp_dir, fanfic_info=fanfic, calibre_info=cdb
    )

    # After attempting to add the story to Calibre, check if the story's ID can be retrieved from Calibre.
    # This serves as a verification step to ensure the story was successfully added.
    if not fanfic.get_id_from_calibredb(cdb):
        # If the story's ID cannot be retrieved, log the failure and handle it accordingly.
        # This might involve sending a notification about the failure and possibly re-queuing the story for another attempt.
        ff_logging.log_failure(
            f"\t({site}) Failed to add {path_or_url} to Calibre"
        )
        handle_failure(fanfic, notification_info, waiting_queue)
    else:
        # If the story was successfully added to Calibre, send a notification about the new download.
        # This notification includes the story's title and the site it was downloaded from.
        notification_info.send_notification(
            "New Fanfiction Download", fanfic.title, site
        )


def url_worker(
    queue: mp.Queue,
    cdb: calibre_info.CalibreInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    waiting_queue: mp.Queue,
) -> None:
    """
    Worker function that processes fanfics from a queue, updating them in a Calibre
    database.

    This function continuously monitors a queue for fanfic objects, processes each
    fanfic by updating its information using the FanFicFare tool, and handles
    failures or necessary retries. It uses a temporary directory for operations
    that require filesystem access. Notifications of successes or failures are sent
    via the Notification Class.

    Args:
        queue (mp.Queue): The queue from which fanfic objects are consumed.
        cdb (calibre_info.CalibreInfo): Information about the Calibre database
            where fanfics are stored.
        notification_info (notification_wrapper.NotificationWrapper): The object for sending notifications.
        waiting_queue (mp.Queue): A queue for fanfics that need to be retried.

    Returns:
        None
    """
    while True:
        # Check if the queue is empty; if so, wait before checking again
        if queue.empty():
            sleep(5)
            continue

        # Retrieve the next fanfic object from the queue
        fanfic = queue.get()
        # If the retrieved item is None, skip to the next iteration
        if fanfic is None:
            continue

        # Use a temporary directory for processing the fanfic
        with system_utils.temporary_directory() as temp_dir:
            site = fanfic.site  # Extract the site from the fanfic object
            ff_logging.log(f"({site}) Processing {fanfic.url}", "HEADER")
            # Determine the path or URL for updating the fanfic
            path_or_url = get_path_or_url(fanfic, cdb, temp_dir)
            ff_logging.log(f"\t({site}) Updating {path_or_url}", "OKGREEN")

            # Construct the command for updating the fanfic with FanFicFare
            command = f'cd {temp_dir} && python -m fanficfare.cli -u "{path_or_url}" --update-cover --non-interactive'
            if fanfic.behavior == "force":
                command += " --force"

            try:
                # Copy necessary configuration files to the temporary directory and execute the update command
                system_utils.copy_configs_to_temp_dir(cdb, temp_dir)
                output = execute_command(command)
            except Exception as e:
                # Log failure and handle it (e.g., by sending a notification or re-queuing the fanfic)
                ff_logging.log_failure(
                    f"\t({site}) Failed to update {path_or_url}: {e}"
                )
                handle_failure(fanfic, notification_info, waiting_queue)
                continue

            # Check the output for failure patterns; if found, handle the failure
            if not regex_parsing.check_failure_regexes(output):
                handle_failure(fanfic, notification_info, waiting_queue)
                continue

            # If the output indicates a retry might succeed, adjust the fanfic's behavior and re-queue it
            if regex_parsing.check_forceable_regexes(output):
                fanfic.behavior = "force"
                queue.put(fanfic)
                continue

            # Process the successful addition of the fanfic to the Calibre database
            process_fanfic_addition(
                fanfic,
                cdb,
                temp_dir,
                site,
                path_or_url,
                waiting_queue,
                notification_info,
            )
