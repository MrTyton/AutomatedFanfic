from subprocess import CalledProcessError, check_output, PIPE, STDOUT
from typing import Optional, Tuple

import calibre_info
import ff_logging


class FanficInfo:
    """
    Represents information about a fanfiction story, including its URL, site, and
    Calibre database ID.

    Attributes:
        url (str): The URL of the fanfiction story.
        site (str): The site where the fanfiction is hosted.
        calibre_id (Optional[str]): The ID of the story in the Calibre database, if
            it exists.
        repeats (Optional[int]): The number of times the story has been processed.
            Defaults to 0.
        max_repeats (Optional[int]): The maximum number of times the story should
            be processed. Defaults to 10.
        behavior (Optional[str]): Custom behavior for processing the story.
        title (Optional[str]): The title of the story.
    """

    def __init__(
        self,
        url: str,
        site: str,
        calibre_id: Optional[str] = None,
        repeats: Optional[int] = 0,
        max_repeats: Optional[int] = 10,
        behavior: Optional[str] = None,
        title: Optional[str] = None,
    ):
        """
        Initializes a FanficInfo object with the provided story details.
        """
        self.url = url
        self.calibre_id = calibre_id
        self.site = site
        self.repeats = repeats
        self.max_repeats = max_repeats
        self.behavior = behavior
        self.title = title
        self.hail_mary = False

    def increment_repeat(self) -> None:
        """
        Increments the repeat counter by one.
        """
        if self.repeats is not None:
            self.repeats += 1

    def reached_maximum_repeats(self) -> Tuple[bool, bool]:
        """
        Checks if the story has reached or exceeded the maximum number of repeats
        allowed.

        Returns:
            bool: If maximum repeats have been reached.
            bool: If hail-mary protocol is enabled.
        """
        if self.repeats is None or self.max_repeats is None:
            return False, False
        if self.repeats >= self.max_repeats:
            if self.hail_mary:
                return True, True
            else:
                ff_logging.log(
                    f"\t({self.site}) Story has been repeated {self.repeats} times. "
                    f"Max repeats is {self.max_repeats}."
                    "Enabling Hail-Mary protocol, will give one more attempt in 12 hours.",
                    "WARNING",
                )
                self.hail_mary = True
                self.repeats = 720
                return True, False
        return False, False

    def get_id_from_calibredb(
        self, calibre_information: calibre_info.CalibreInfo
    ) -> bool:
        """
        Attempts to find the story's ID in the Calibre database using its URL.

        Args:
            calibre_information (calibre_info.CalibreInfo): Information about the
                Calibre database.

        Returns:
            bool: True if the story is found in the Calibre database, False otherwise.
        """
        try:
            with calibre_information.lock:
                story_id = check_output(
                    f'calibredb search "Identifiers:{self.url}" {calibre_information}',
                    shell=True,
                    stderr=STDOUT,
                    stdin=PIPE,
                ).decode("utf-8")

            self.calibre_id = story_id.strip()
            ff_logging.log(
                f"\t({self.site}) Story is in Calibre with Story ID: {self.calibre_id}",
                "OKBLUE",
            )
            return True
        except CalledProcessError:
            ff_logging.log(f"\t({self.site}) Story not in Calibre", "WARNING")
            return False

    def __eq__(self, other: object) -> bool:
        """
        Checks if another object is equal to this FanficInfo instance.

        Args:
            other (object): The object to compare with.

        Returns:
            bool: True if the other object is a FanficInfo instance with the same URL,
                site, and Calibre ID, False otherwise.
        """
        if not isinstance(other, FanficInfo):
            return False
        return (
            self.url == other.url
            and self.site == other.site
            and self.calibre_id == other.calibre_id
        )

    def __hash__(self) -> int:
        """
        Returns a hash value for this FanficInfo instance.

        The hash value is computed based on the URL, site, and Calibre ID of the story.

        Returns:
            int: The hash value of the FanficInfo instance.
        """
        return hash((self.url, self.site, self.calibre_id))
