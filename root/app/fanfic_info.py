"""Fanfiction story metadata and processing state management.

This module defines the core FanficInfo class that represents individual fanfiction
stories throughout their processing lifecycle in the AutomatedFanfic application.
It encapsulates story metadata, retry state management, Calibre integration, and
comprehensive behavior tracking for the automated download and update system.

Key Features:
    - Story metadata encapsulation (URL, site, Calibre ID, behavior state)
    - Retry logic with exponential backoff and Hail-Mary protocol support
    - Calibre database integration for story existence checking and ID retrieval
    - Thread-safe equality and hashing based on story identifiers
    - Serializable design for multiprocessing queue communication

Classes:
    FanficInfo: Complete story representation with processing state management

The FanficInfo class serves as the primary data structure passed between worker
processes in the multiprocessing architecture, maintaining all necessary state
for fanfiction download, update, retry, and Calibre integration workflows.
"""

from subprocess import CalledProcessError, check_output, PIPE, STDOUT
from typing import Optional, Tuple

import calibre_info
import ff_logging


class FanficInfo:
    """Represents metadata and processing state for a fanfiction story.

    This class encapsulates all information about a fanfiction story including
    its source URL, hosting site, Calibre database integration, and retry logic.
    It provides methods for managing the story's processing lifecycle, including
    retry counting, Hail-Mary protocol activation, and Calibre database lookups.

    The class implements equality and hashing based on URL, site, and Calibre ID
    to enable proper deduplication and set operations in processing workflows.

    Attributes:
        url (str): The canonical URL of the fanfiction story.
        site (str): The hosting site identifier (e.g., 'fanfiction', 'archiveofourown').
        calibre_id (Optional[str]): The unique ID in the Calibre database if the
            story exists there, None if not found or not yet searched.
        repeats (Optional[int]): Current retry count for failed processing attempts.
        max_repeats (Optional[int]): Maximum allowed retry attempts before giving up.
        behavior (Optional[str]): Special processing behavior flag (e.g., 'force').
        title (Optional[str]): The extracted or provided title of the story.
        hail_mary (bool): Whether the Hail-Mary protocol has been activated for
            this story, providing one final retry attempt after extended delay.

    Note:
        The Hail-Mary protocol is activated when max_repeats is reached, providing
        one additional retry attempt after a 12-hour delay (720 minutes).
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
        """Initializes a FanficInfo object with story metadata and processing state.

        Creates a new fanfiction story object with the provided metadata and
        sets up the initial processing state. The retry mechanism is initialized
        with sensible defaults, and the Hail-Mary protocol is disabled initially.

        Args:
            url (str): The canonical URL of the fanfiction story. Should be the
                clean URL without query parameters or fragments.
            site (str): The hosting site identifier used for routing to appropriate
                processing workers (e.g., 'fanfiction', 'archiveofourown').
            calibre_id (Optional[str], optional): The Calibre database ID if known.
                Defaults to None, will be populated during database lookup.
            repeats (Optional[int], optional): Initial retry count. Defaults to 0
                for new stories.
            max_repeats (Optional[int], optional): Maximum retry attempts before
                activating Hail-Mary protocol. Defaults to 10.
            behavior (Optional[str], optional): Special processing behavior flag
                such as 'force' for forced updates. Defaults to None.
            title (Optional[str], optional): The story title if known. Defaults
                to None, will be extracted during processing.

        Note:
            The hail_mary attribute is automatically initialized to False and
            managed by the reached_maximum_repeats() method.
        """
        self.url = url
        self.calibre_id = calibre_id
        self.site = site
        self.repeats = repeats
        self.max_repeats = max_repeats
        self.behavior = behavior
        self.title = title
        # Initialize Hail-Mary protocol as disabled
        self.hail_mary = False

    def increment_repeat(self) -> None:
        """Increments the retry counter for failed processing attempts.

        Increases the repeats counter by one to track the number of failed
        processing attempts for this story. This counter is used by the
        retry logic to determine when to activate the Hail-Mary protocol
        or abandon processing entirely.

        Note:
            If repeats is None, this method safely handles the case by
            checking for None before incrementing. This prevents errors
            in edge cases where the retry system is disabled.
        """
        if self.repeats is not None:
            # Safely increment the retry counter
            self.repeats += 1

    def reached_maximum_repeats(self) -> Tuple[bool, bool]:
        """Evaluates retry status and manages the Hail-Mary protocol activation.

        Determines if the story has reached its maximum retry limit and handles
        the transition to the Hail-Mary protocol. This method implements a
        two-stage retry system: normal retries up to max_repeats, followed by
        one final Hail-Mary attempt after an extended delay.

        The Hail-Mary protocol provides one additional retry opportunity for
        stories that have exhausted their normal retry allocation, with a
        12-hour delay (720 minutes) to allow for potential site recovery.

        Returns:
            Tuple[bool, bool]: A tuple containing:
                - First boolean: True if maximum repeats have been reached
                - Second boolean: True if Hail-Mary protocol has been activated
                  and this is the final attempt

        Note:
            When Hail-Mary is activated, the repeats counter is set to 720 to
            implement the 12-hour delay through the existing retry timing logic.
            This clever reuse of the retry system provides the extended delay
            without additional complexity.
        """
        # Handle cases where retry limits are not configured
        if self.repeats is None or self.max_repeats is None:
            return False, False

        # Check if we've reached the maximum retry limit
        if self.repeats >= self.max_repeats:
            # If Hail-Mary is already active, this is the final attempt
            if self.hail_mary:
                return True, True
            else:
                # Activate Hail-Mary protocol for one final attempt
                ff_logging.log(
                    f"\t({self.site}) Story has been repeated {self.repeats} times. "
                    f"Max repeats is {self.max_repeats}."
                    "Enabling Hail-Mary protocol, will give one more attempt in 12 hours.",
                    "WARNING",
                )
                self.hail_mary = True
                # Set repeats to 720 (12 hours in minutes) for extended delay
                self.repeats = 720
                return True, False

        # Normal case: retry limit not yet reached
        return False, False

    def get_id_from_calibredb(
        self, calibre_information: calibre_info.CalibreInfo
    ) -> bool:
        """Searches for the story in the Calibre database and retrieves its ID.

        Performs a database search using the story's URL as an identifier to
        determine if the story already exists in the Calibre library. If found,
        the calibre_id attribute is updated with the database ID for future
        operations like updates or exports.

        This method uses thread-safe database access through the calibre_information
        lock to prevent concurrent database modifications that could cause
        corruption or inconsistent results.

        Args:
            calibre_information (calibre_info.CalibreInfo): Configuration object
                containing Calibre database connection details, authentication
                credentials, and the thread safety lock.

        Returns:
            bool: True if the story was found in the Calibre database and
                calibre_id was successfully set, False if the story is not
                in the database or the search failed.

        Note:
            The search uses the story URL as a unique identifier in Calibre's
            Identifiers field. This assumes that URLs are used as the primary
            identification method for fanfiction stories in the library.

        Raises:
            This method catches CalledProcessError internally and returns False
            rather than propagating exceptions, ensuring robust error handling
            in the calling code.
        """
        try:
            # Acquire database lock to ensure thread-safe access
            with calibre_information.lock:
                # Execute calibredb search using URL as identifier
                story_id = check_output(
                    f'calibredb search "Identifiers:{self.url}" {calibre_information}',
                    shell=True,
                    stderr=STDOUT,
                    stdin=PIPE,
                ).decode("utf-8")

            # Clean and store the retrieved database ID
            self.calibre_id = story_id.strip()
            ff_logging.log(
                f"\t({self.site}) Story is in Calibre with Story ID: {self.calibre_id}",
                "OKBLUE",
            )
            return True
        except CalledProcessError:
            # Handle case where story is not found in database
            ff_logging.log(f"\t({self.site}) Story not in Calibre", "WARNING")
            return False

    def __eq__(self, other: object) -> bool:
        """Determines equality between FanficInfo instances based on key identifiers.

        Compares this FanficInfo instance with another object to determine if they
        represent the same fanfiction story. Equality is based on the combination
        of URL, site, and Calibre ID, which together uniquely identify a story
        within the processing system.

        This method enables proper deduplication in sets and dictionaries, ensuring
        that the same story isn't processed multiple times even if multiple
        FanficInfo objects are created for it.

        Args:
            other (object): The object to compare with this FanficInfo instance.
                Can be any type, but only FanficInfo instances can be equal.

        Returns:
            bool: True if the other object is a FanficInfo instance with identical
                URL, site, and calibre_id values, False otherwise.

        Note:
            This method follows Python's equality contract and is consistent with
            the __hash__ method, ensuring that equal objects have equal hash values.
        """
        # Type check to ensure we're comparing with another FanficInfo
        if not isinstance(other, FanficInfo):
            return False

        # Compare the three key identifying attributes
        return (
            self.url == other.url
            and self.site == other.site
            and self.calibre_id == other.calibre_id
        )

    def __hash__(self) -> int:
        """Generates a hash value for FanficInfo instances to enable use in sets and dictionaries.

        Computes a hash based on the URL, site, and Calibre ID fields that are
        used for equality comparison. This ensures that FanficInfo objects can
        be properly stored in sets and used as dictionary keys, with consistent
        behavior relative to the __eq__ method.

        The hash is immutable-safe since it's based on identifying attributes
        that shouldn't change during the object's lifetime in normal usage.

        Returns:
            int: A hash value computed from the tuple of (url, site, calibre_id).
                Equal FanficInfo instances will always produce the same hash value.

        Note:
            This method is consistent with __eq__, meaning that if two FanficInfo
            objects are equal, they will have the same hash value. This is required
            for proper behavior in Python collections.
        """
        # Create hash from the same attributes used in equality comparison
        return hash((self.url, self.site, self.calibre_id))
