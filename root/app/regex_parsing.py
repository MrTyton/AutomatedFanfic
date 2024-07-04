import os
import re
import fanfic_info
import ff_logging

# Define regular expressions for different URL formats
url_parsers = {
    "ffnet": (re.compile(r"(fanfiction.net/s/\d*/?).*"), "www."),
    "ao3": (re.compile(r"(archiveofourown.org/works/\d*)/?.*"), ""),
    "fictionpress": (re.compile(r"(fictionpress.com/s/\d*)/?.*"), ""),
    "royalroad": (re.compile(r"(royalroad.com/fiction/\d*)/?.*"), ""),
    "sv": (re.compile(r"(forums.sufficientvelocity.com/threads/.*\.\d*)/?.*"), ""),
    "sb": (re.compile(r"(forums.spacebattles.com/threads/.*\.\d*)/?.*"), ""),
    "qq": (re.compile(r"(forum.questionablequesting.com/threads/.*\.\d*)/?.*"), ""),
    "other": (re.compile(r"https?://(.*)"), ""),
}

# Define regular expressions for different story formats and errors
story_name = re.compile(r"(.*?)-.*")
equal_chapters = re.compile(r".* already contains (\d+) chapters.")
chapter_difference = re.compile(r".* contains (\d+) chapters, more than source: (\d+).")
bad_chapters = re.compile(
    r".* doesn't contain any recognizable chapters, probably from a different source.  Not updating."
)
no_url = re.compile(r"No story URL found in epub to update.")
more_chapters = re.compile(
    r".*File\(.*\.epub\) Updated\(.*\) more recently than Story\(.*\) - Skipping"
)
failed_login = re.compile(
    r".*Login Failed on non-interactive process. Set username and password in personal.ini."
)
bad_request = re.compile(r".*400 Client Error: Bad Request for url:.*")
forbidden_client = re.compile(r".*403 Client Error: Forbidden for url:.*")
flaresolverr = re.compile(r".*Connection to flaresolverr proxy server failed.*")


def extract_filename(filename: str) -> str:
    """
    Extracts the title from the filename.

    Args:
        filename (str): The filename from which to extract the title.

    Returns:
        str: The extracted title or the original filename if no title is found.
    """
    basenamed_filepath = os.path.basename(filename)
    match = story_name.search(basenamed_filepath)
    return match.group(1).strip() if match else basenamed_filepath.strip()


def check_regexes(output: str, regex: re.Pattern, message: str) -> bool:
    """
    Checks if the given output matches the provided regular expression and logs a
    failure message if it does.

    Args:
        output (str): The output to check against the regex.
        regex (re.Pattern): The regular expression to match against the output.
        message (str): The failure message to log if the regex matches.

    Returns:
        bool: True if the regex matches the output, False otherwise.
    """
    if regex.search(output):
        ff_logging.log_failure(message)
        return True
    return False


def check_failure_regexes(output: str) -> bool:
    """
    Checks if the given output matches any of the predefined failure regular
    expressions.

    Args:
        output (str): The output to check against the failure regexes.

    Returns:
        bool: True if none of the failure regexes match, indicating no failure
        detected.
    """
    failure_regexes = [
        (
            equal_chapters,
            "Issue with story, site is broken. Story likely hasn't updated on site yet.",
        ),
        (
            bad_chapters,
            "Something is messed up with the site or the epub. No chapters found.",
        ),
        (no_url, "No URL in epub to update from. Fix the metadata."),
        (failed_login, "Login failed. Check your username and password."),
        (bad_request, "Bad request. Check the URL."),
        (
            forbidden_client,
            "Forbidden client. Check the URL. If this is ff.net, check that you have Flaresolverr installed, or cry.",
        ),
        (
            flaresolverr,
            "Flaresolverr connection failed. Check your Flaresolverr installation.",
        ),
    ]
    return not any(
        check_regexes(output, regex, message) for regex, message in failure_regexes
    )


def check_forceable_regexes(output: str) -> bool:
    """
    Checks if the given output matches any of the predefined forceable regular
    expressions.

    Args:
        output (str): The output to check against the forceable regexes.

    Returns:
        bool: True if any of the forceable regexes match, indicating a condition
        that can be forced.
    """
    forceable_regexes = [
        (
            chapter_difference,
            "Chapter difference between source and destination. Forcing update.",
        ),
        (
            more_chapters,
            "File has been updated more recently than the story, this is likely a metadata bug. Forcing update.",
        ),
    ]
    return any(
        check_regexes(output, regex, message) for regex, message in forceable_regexes
    )


def generate_FanficInfo_from_url(url: str) -> fanfic_info.FanficInfo:
    """
    Generates a FanficInfo object from a given URL by identifying the site and
    adjusting the URL if necessary.

    Args:
        url (str): The URL to generate FanficInfo from.

    Returns:
        fanfic_info.FanficInfo: The generated FanficInfo object.
    """
    for site, (parser, prefix) in url_parsers.items():
        if match := parser.search(url):
            url = prefix + match.group(1)
            return fanfic_info.FanficInfo(url, site)
    return fanfic_info.FanficInfo(url, "other")
