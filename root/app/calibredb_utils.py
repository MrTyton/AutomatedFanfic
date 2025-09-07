import fanfic_info
import calibre_info
import ff_logging
import regex_parsing
import system_utils
from subprocess import call, PIPE, DEVNULL
from typing import Optional


def call_calibre_db(
    command: str,
    calibre_info: calibre_info.CalibreInfo,
    fanfic_info: Optional[fanfic_info.FanficInfo] = None,
):
    """
    Calls the calibre database with a specific command.

    Args:
        command (str): The command to be executed on the calibre database.
        calibre_info (calibre_info.CalibreInfo): The calibre information object.
        fanfic_info (fanfic_info.FanficInfo): The fanfic information object.

    Returns:
        None
    """
    ff_logging.log_debug(
        f'\tCalling calibredb with command: \t"{command} {fanfic_info.calibre_id if fanfic_info else ""} {calibre_info}"'
    )
    try:
        # Lock the calibre database to prevent concurrent modifications
        with calibre_info.lock:
            # Call the calibre command line tool with the specified command\
            call(
                f"calibredb {command} {fanfic_info.calibre_id if fanfic_info else ''} {calibre_info}",
                shell=True,
                stdin=PIPE,
                stdout=DEVNULL,
                stderr=DEVNULL,
            )
    except Exception as e:
        # Log any failures
        ff_logging.log_failure(
            f'\t"{command} {fanfic_info.calibre_id if fanfic_info else ""} {calibre_info}" failed: {e}'
        )


def export_story(
    *,
    fanfic_info: fanfic_info.FanficInfo,
    location: str,
    calibre_info: calibre_info.CalibreInfo,
) -> None:
    """
    Exports a story from the Calibre library to a specified location.

    This function constructs and executes a command to export a story from the
    Calibre library, placing the exported file(s) into the specified directory. It
    ensures that the cover and OPF files are not saved during the export, and all
    files are placed in a single directory.

    Args:
        fanfic_info (fanfic_info.FanficInfo): An object containing information
            about the fanfic to be exported.
        location (str): The target directory path where the story should be
            exported.
        calibre_info (calibre_info.CalibreInfo): An object containing information
            about the Calibre library.

    Returns:
        None: The function does not return any value.
    """
    # Construct the command for exporting the story, specifying not to save cover or OPF, and to use a single directory
    command = (
        f'export --dont-save-cover --dont-write-opf --single-dir --to-dir "{location}"'
    )

    # Execute the command to export the story from Calibre to the specified location
    call_calibre_db(command, calibre_info, fanfic_info)


def remove_story(
    fanfic_info: fanfic_info.FanficInfo, calibre_info: calibre_info.CalibreInfo
) -> None:
    """
    Removes a story from the Calibre library based on the information provided in
    fanfic_info.

    This function interfaces with the Calibre database to remove a specific story.
    It utilizes the unique identifier or metadata associated with the fanfic_info
    object to locate and remove the story from the Calibre library.

    Args:
        fanfic_info (fanfic_info.FanficInfo): An object containing information
            about the fanfic to be removed.
        calibre_info (calibre_info.CalibreInfo): An object containing information
            about the Calibre library from which the story will be removed.

    Returns:
        None: This function does not return a value but removes the specified story
        from the Calibre library.
    """
    # Utilize a helper function to call the Calibre database's "remove" command with the necessary information
    call_calibre_db("remove", calibre_info, fanfic_info)


def add_story(
    *,
    location: str,
    fanfic_info: fanfic_info.FanficInfo,
    calibre_info: calibre_info.CalibreInfo,
) -> None:
    """
    Adds a story to the Calibre library from a specified location.

    This function searches for the first EPUB file within the given location and
    attempts to add it to the Calibre library. It logs the process and handles
    potential errors. The title of the fanfic is updated based on the filename of
    the EPUB.

    Args:
        location (str): The directory where the story file is located.
        fanfic_info (fanfic_info.FanficInfo): The fanfic information object.
        calibre_info (calibre_info.CalibreInfo): The calibre information object.

    Returns:
        None
    """
    # Find the first EPUB file in the specified location
    epub_files = system_utils.get_files(
        location, file_extension="epub", return_full_path=True
    )
    if not epub_files:
        ff_logging.log_failure("No EPUB files found in the specified location.")
        return

    file_to_add = epub_files[0]

    # Extract and update the fanfic title from the filename
    fanfic_info.title = regex_parsing.extract_filename(file_to_add)

    # Log the addition attempt
    ff_logging.log(f"\t({fanfic_info.site}) Adding {file_to_add} to Calibre", "OKGREEN")
    command = f'add -d {calibre_info} "{file_to_add}"'
    call_calibre_db(command, calibre_info, fanfic_info=None)
