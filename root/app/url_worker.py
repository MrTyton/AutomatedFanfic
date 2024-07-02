from contextlib import contextmanager
import multiprocessing as mp
import os
from os.path import isfile, join
from shutil import rmtree, copyfile
from subprocess import call, check_output, PIPE, STDOUT, DEVNULL
from tempfile import mkdtemp
from time import sleep

import calibre_info
import fanfic_info
import ff_logging
import pushbullet_notification
import regex_parsing

@contextmanager
def temporary_directory():
    """Create and clean up a temporary directory."""
    temp_dir = mkdtemp()
    try:
        yield temp_dir
    finally:
        rmtree(temp_dir)

def call_calibre_db(command: str, fanfic_info: fanfic_info.FanficInfo, calibre_info: calibre_info.CalibreInfo):
    """
    Call the calibre database with a specific command.

    Parameters:
    command (str): The command to be executed on the calibre database.
    fanfic_info (fanfic_info.FanficInfo): The fanfic information object.
    calibre_info (calibre_info.CalibreInfo): The calibre information object.

    Returns:
    None
    """
    try:
        # Lock the calibre database to prevent concurrent modifications
        with calibre_info.lock:
            # Call the calibre command line tool with the specified command\
            #ff_logging.log(f"\tCommand: calibredb {command} {fanfic_info.calibre_id} {calibre_info}", "OKBLUE")
            call(
                f"calibredb {command} {fanfic_info.calibre_id} {calibre_info}",
                shell=True,
                stdin=PIPE,
                stdout=DEVNULL,
                stderr=DEVNULL,
            )
    except Exception as e:
        # Log any failures
        ff_logging.log_failure(f"\tFailed to {command} {fanfic_info.calibre_id} from Calibre: {e}")

def export_story(*, fanfic_info: fanfic_info.FanficInfo, location: str, calibre_info: calibre_info.CalibreInfo) -> None:
    """
    Export a story from the Calibre library to a specified location.

    Parameters:
    fanfic_info (fanfic_info.FanficInfo): The fanfic information object.
    location (str): The directory to which the story should be exported.
    calibre_info (calibre_info.CalibreInfo): The calibre information object.

    Returns:
    None
    """
    # Define the command to be executed
    command = f'export --dont-save-cover --dont-write-opf --single-dir --to-dir "{location}"'
    # Call the calibre database with the specified command
    call_calibre_db(command, fanfic_info, calibre_info)
    
def remove_story(*, fanfic_info: fanfic_info.FanficInfo, calibre_info: calibre_info.CalibreInfo) -> None:
    """
    Remove a story from the Calibre library.

    Parameters:
    fanfic_info (fanfic_info.FanficInfo): The fanfic information object.
    calibre_info (calibre_info.CalibreInfo): The calibre information object.

    Returns:
    None
    """
    # Call the calibre database with the "remove" command
    call_calibre_db("remove", fanfic_info, calibre_info)

def add_story(*, location: str, fanfic_info: fanfic_info.FanficInfo, calibre_info: calibre_info.CalibreInfo,) -> None:
    """
    Add a story to the Calibre library.

    Parameters:
    location (str): The directory where the story file is located.
    fanfic_info (fanfic_info.FanficInfo): The fanfic information object.
    calibre_info (calibre_info.CalibreInfo): The calibre information object.

    Returns:
    None
    """
    # Get the first epub file in the location
    file_to_add = get_files(location, file_extension=".epub", return_full_path=True)[0]
    
    # Log the file being added
    ff_logging.log(f"\tAdding {file_to_add} to Calibre", "OKGREEN")
    
    try:
        # Lock the calibre database to prevent concurrent modifications
        with calibre_info.lock:
            # Call the calibre command line tool to add the story
            fanfic_info.title = regex_parsing.extract_filename(get_files(location, file_extension=".epub")[0])
            call(
                f'calibredb add -d {calibre_info} "{file_to_add}"',
                shell=True,
                stdin=PIPE,
                stderr=STDOUT,
            )
        # Update the title of the fanfic_info object
    except Exception as e:
        # Log any failures
        ff_logging.log_failure(f"\tFailed to add {file_to_add} to Calibre: {e}")
    

def continue_failure(fanfic: fanfic_info.FanficInfo, pushbullet: pushbullet_notification.PushbulletNotification, queue: mp.Queue) -> None:
    """
    Handle a failure by either logging a failure and returning, or incrementing the repeat count and putting the fanfic back in the queue.

    Parameters:
    fanfic (fanfic_info.FanficInfo): The fanfic information object.
    pushbullet (pushbullet_notification.PushbulletNotification): The pushbullet notification object.
    queue (mp.Queue): The multiprocessing queue object.

    Returns:
    None
    """
    # If the fanfic has reached the maximum number of repeats, log a failure and return
    if fanfic.reached_maximum_repeats():
        ff_logging.log_failure(f"Reached maximum number of repeats for {fanfic.url}. Skipping.")
        pushbullet.send_notification("Fanfiction Download Failed", fanfic.url, fanfic.site)
    else:
        # Increment the repeat count and put the fanfic back in the queue
        fanfic.increment_repeat()
        queue.put(fanfic)
        
def get_files(directory_path, file_extension=None, return_full_path=False):
    """
    Get files from a directory. If a file extension is specified, filter files by extension.

    Parameters:
    directory_path (str): The path of the directory from which to get files.
    file_extension (str, optional): The extension of the files to get. Defaults to None.
    return_full_path (bool, optional): Whether to return the full path of the files. Defaults to False.

    Returns:
    list: A list of file names or file paths, depending on the value of return_full_path.
    """
    # Get a list of files in the directory that have the specified extension (or all files if no extension is specified)
    files = [
        file
        for file in os.listdir(directory_path)
        if isfile(join(directory_path, file)) and (not file_extension or file.endswith(file_extension))
    ]
    
    # If return_full_path is True, replace the list of file names with a list of file paths
    if return_full_path:
        files = [join(directory_path, file) for file in files]
    
    return files

def get_path_or_url(ff_info: fanfic_info.FanficInfo, cdb_info: calibre_info.CalibreInfo, location: str = "") -> str:
    """
    Get the path of the exported story if it exists in the Calibre library, otherwise return the URL of the story.

    Parameters:
    ff_info (fanfic_info.FanficInfo): The fanfic information object.
    cdb_info (calibre_info.CalibreInfo): The calibre information object.
    location (str, optional): The directory to which the story should be exported. Defaults to "".

    Returns:
    str: The path of the exported story or the URL of the story.
    """
    # If the story exists in the Calibre library
    if ff_info.get_id_from_calibredb(cdb_info):
        # Export the story to the specified location
        export_story(fanfic_info=ff_info, location=location, calibre_info=cdb_info)
        # Return the path of the exported story
        return get_files(location, file_extension=".epub", return_full_path=True)[0]
    # If the story does not exist in the Calibre library, return the URL of the story
    return ff_info.url

def url_worker(queue: mp.Queue, cdb: calibre_info.CalibreInfo, pushbullet_info: pushbullet_notification.PushbulletNotification, waiting_queue: mp.Queue) -> None:
    """
    Worker function that updates fanfics from a queue.

    Parameters:
    queue (mp.Queue): The multiprocessing queue object.
    cdb (calibre_info.CalibreInfo): The calibre information object.
    pushbullet_info (pushbullet_notification.PushbulletNotification): The pushbullet notification object.

    Returns:
    None
    """
    # Continuously process fanfics from the queue
    while True:
        # If the queue is empty, sleep for 5 seconds and then continue to the next iteration
        if queue.empty():
            sleep(5)
            continue

        # Get a fanfic from the queue
        fanfic: fanfic_info.FanficInfo = queue.get()
        # If the fanfic is None, continue to the next iteration
        if fanfic is None:
            continue

        # Create a temporary directory
        with temporary_directory() as temp_dir:
            
            site = fanfic.site
            
            ff_logging.log(f"({site}) Processing {fanfic.url}", "HEADER")

            # Get the path of the fanfic if it exists in the Calibre library, otherwise get the URL of the fanfic
            path_or_url = get_path_or_url(fanfic, cdb, temp_dir)

            # Log the update
            ff_logging.log(f"\t({site}) Updating {path_or_url}", "OKGREEN")

            # Define the command to update the fanfic
            command = f'cd {temp_dir} && python -m fanficfare.cli -u "{path_or_url}" --update-cover --non-interactive'
            # If the behavior of the fanfic is "force", add the "--force" option to the command
            if fanfic.behavior == "force":
                command += " --force"

            #ff_logging.log(f"\t({site}) Running Command: {command}", "OKBLUE")
            try:
                #copy the configs to the temp directory
                if cdb.default_ini:
                    copyfile(cdb.default_ini, join(temp_dir, "defaults.ini"))
                if cdb.personal_ini:
                    copyfile(cdb.personal_ini, join(temp_dir, "personal.ini"))
                # Execute the command and get the output
                output = check_output(command, shell=True, stderr=STDOUT, stdin=PIPE).decode("utf-8")
                #ff_logging.log(f"\t({site}) Output: {output}", "OKBLUE")
            except Exception as e:
                # If the command fails, log the failure and continue to the next iteration
                ff_logging.log_failure(f"\t({site}) Failed to update {path_or_url}: {e}, {output}")
                continue_failure(fanfic, pushbullet_info, waiting_queue)
                continue

            # If the output indicates a failure, continue to the next iteration
            if not regex_parsing.check_failure_regexes(output):
                continue_failure(fanfic, pushbullet_info, waiting_queue)
                continue
            # If the output indicates a forceable error, set the behavior of the fanfic to "force" and put it back in the queue
            if regex_parsing.check_forceable_regexes(output):
                fanfic.behavior = "force"
                queue.put(fanfic)
                continue

            # If the fanfic exists in the Calibre library, remove it
            if fanfic.calibre_id:
                ff_logging.log(f"\t({site}) Going to remove story from Calibre.", "OKGREEN")
                remove_story(fanfic_info=fanfic, calibre_info=cdb)
            # Add the fanfic to the Calibre library
            add_story(location=temp_dir, fanfic_info=fanfic, calibre_info=cdb)

            # If the fanfic was not added to the Calibre library, log a failure and continue to the next iteration
            if not fanfic.get_id_from_calibredb(cdb):
                ff_logging.log_failure(f"\t({site}) Failed to add {path_or_url} to Calibre")
                continue_failure(fanfic, pushbullet_info, waiting_queue)
            else:
                # If the fanfic was added to the Calibre library, send a notification
                pushbullet_info.send_notification("New Fanfiction Download", fanfic.title, site)
