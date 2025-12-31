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

from typing import Optional

from models import retry_types


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
        behavior (Optional[str]): Special processing behavior flag (e.g., 'force').
        title (Optional[str]): The extracted or provided title of the story.

    Note:
        This class now focuses solely on maintaining the current state of a story.
        Retry logic and failure action determination are handled externally by
        specialized components that can access configuration and make decisions
        based on the current state stored here.
    """

    def __init__(
        self,
        url: str,
        site: str,
        calibre_id: Optional[str] = None,
        repeats: Optional[int] = 0,
        behavior: Optional[str] = None,
        title: Optional[str] = None,
        retry_decision: Optional[retry_types.RetryDecision] = None,
    ):
        """Initializes a FanficInfo object with story metadata and current state.

        Creates a new fanfiction story object with the provided metadata and
        sets up the initial processing state. The object focuses on maintaining
        current state information; retry logic and failure decisions are handled
        by external components with access to configuration.

        Args:
            url (str): The canonical URL of the fanfiction story. Should be the
                clean URL without query parameters or fragments.
            site (str): The hosting site identifier used for routing to appropriate
                processing workers (e.g., 'fanfiction', 'archiveofourown').
            calibre_id (Optional[str], optional): The Calibre database ID if known.
                Defaults to None, will be populated during database lookup.
            repeats (Optional[int], optional): Initial retry count. Defaults to 0
                for new stories.
            behavior (Optional[str], optional): Special processing behavior flag
                such as 'force' for forced updates. Defaults to None.
            title (Optional[str], optional): The story title if known. Defaults
                to None, will be extracted during processing.
            retry_decision (Optional[retry_types.RetryDecision], optional): The
                last retry decision made for this story, including delay timing
                and notification requirements. Defaults to None.

        Note:
            This simplified design removes retry configuration from the story
            object itself. Retry decisions are now made externally by components
            that have access to both the current state and configuration settings.
            The retry_decision field stores the results to avoid recalculation.
        """
        self.url = url
        self.calibre_id = calibre_id
        self.site = site
        self.repeats = repeats
        self.behavior = behavior
        self.title = title
        self.retry_decision = retry_decision

    def increment_repeat(self) -> None:
        """Increments the retry counter for failed processing attempts.

        Increases the repeats counter by one to track the number of failed
        processing attempts for this story. This counter represents the current
        state and is used by external retry logic components to determine
        appropriate next actions.

        Note:
            If repeats is None, this method safely handles the case by
            checking for None before incrementing. This prevents errors
            in edge cases where the retry system is disabled.
        """
        if self.repeats is not None:
            # Safely increment the retry counter
            self.repeats += 1

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
