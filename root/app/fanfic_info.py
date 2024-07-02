from subprocess import CalledProcessError, check_output, PIPE, STDOUT

from typing import Optional

import calibre_info
import ff_logging

class FanficInfo:
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
        self.url: str = url
        self.calibre_id: Optional[str] = calibre_id
        self.site: str = site
        self.repeats: Optional[int] = repeats
        self.max_repeats: Optional[int] = max_repeats
        self.behavior: Optional[str] = behavior
        self.title: Optional[str] = title

    # Increment the repeat counter
    def increment_repeat(self) -> None:
        if self.repeats is not None:
            self.repeats += 1

    # Check if the URL has been repeated too many times
    def reached_maximum_repeats(self) -> bool:
        if self.repeats is not None and self.max_repeats is not None:
            return self.repeats >= self.max_repeats
        return False

    # Check if the story is in the Calibre database
    def get_id_from_calibredb(
        self, calibre_information: calibre_info.CalibreInfo
    ) -> bool:
        try:
            # Lock the Calibre database to prevent concurrent modifications
            with calibre_information.lock:
                # Search for the story in the Calibre database
                story_id = check_output(
                    f'calibredb search "Identifiers:{self.url}" {calibre_information}',
                    shell=True,
                    stderr=STDOUT,
                    stdin=PIPE,
                ).decode("utf-8")

            # If the story is found, update the id and log a message
            self.calibre_id = story_id
            ff_logging.log(f"\t({self.site}) Story is in Calibre with Story ID: {self.calibre_id}", "OKBLUE")
            return True
        except CalledProcessError:
            # If the story is not found, log a warning
            ff_logging.log(f"\t({self.site}) Story not in Calibre", "WARNING")
            return False
        
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FanficInfo):
            return False
        return self.url == other.url and self.site == other.site and self.calibre_id == other.calibre_id