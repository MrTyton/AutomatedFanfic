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

# Define regular expressions for different story formats
story_name = re.compile(r"(.*?) - .*")
equal_chapters = re.compile(r".* already contains \d* chapters.")
chapter_difference = re.compile(r".* contains \d* chapters, more than source: \d*.")
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
    """Extract the title from the filename."""
    match = story_name.search(filename)
    if match:
        return match.group(1).strip()
    return filename


def check_regexes(output: str, regex: re.Pattern, message: str) -> bool:
    """Check if the output matches the given regular expression."""
    match = regex.search(output)
    if match:
        ff_logging.log_failure(message)
        return True
    return False


def check_failure_regexes(output: str) -> bool:
    """Check if the output matches any of the failure regular expressions."""
    return not any(
        check_regexes(output, regex, message)
        for regex, message in [
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
            (flaresolverr, "Flaresolverr connection failed. Check your Flaresolverr installation.")
        ]
    )


def check_forceable_regexes(output: str) -> bool:
    """Check if the output matches any of the forceable regular expressions."""
    return any(
        check_regexes(output, regex, message)
        for regex, message in [
            (
                chapter_difference,
                "Chapter difference between source and destination. Forcing update.",
            ),
            (
                more_chapters,
                "File has been updated more recently than the story, this is likely a metadata bug. Forcing update.",
            ),
        ]
    )


def generate_FanficInfo_from_url(url: str) -> fanfic_info.FanficInfo:
    """Generate a FanficInfo object from a URL."""
    site = "other"
    for current_site, (current_parser, current_prefix) in url_parsers.items():
        match = current_parser.search(url)
        if match:
            url = current_prefix + match.group(1)
            site = current_site
            break
    return fanfic_info.FanficInfo(url, site)
