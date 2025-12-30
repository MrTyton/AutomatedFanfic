"""
Update strategies for Calibre story management.

This module implements the Strategy pattern for handling different methods of
updating fanfiction stories in the Calibre library. It provides a flexible
way to switch between preservation modes (Metadata, Format Only, or Remove-Add).
"""

from abc import ABC, abstractmethod
import multiprocessing as mp
from typing import Callable

import calibre_info
import calibredb_utils
import config_models
import fanfic_info
import ff_logging
import notification_wrapper


class UpdateStrategy(ABC):
    """Abstract base class for Calibre update strategies."""

    @abstractmethod
    def execute(
        self,
        fanfic: fanfic_info.FanficInfo,
        cdb: calibre_info.CalibreInfo,
        temp_dir: str,
        site: str,
        path_or_url: str,
        waiting_queue: mp.Queue,
        notification_info: notification_wrapper.NotificationWrapper,
        retry_config: config_models.RetryConfig,
        failure_handler: Callable,
    ) -> bool:
        """
        Execute the update strategy.

        Args:
            fanfic: Fanfiction information object
            cdb: Calibre database configuration
            temp_dir: Temporary directory with downloaded story
            site: Site identifier for logging
            path_or_url: Path or URL being processed
            waiting_queue: Queue for retry handling
            notification_info: Notification system
            retry_config: Retry configuration
            failure_handler: Callable to handle failures (typically handle_failure from url_worker)

        Returns:
            bool: True if successful, False if failed
        """
        pass


class AddFormatStrategy(UpdateStrategy):
    """Strategy for ADD_FORMAT preservation mode - replace EPUB file only."""

    def execute(
        self,
        fanfic: fanfic_info.FanficInfo,
        cdb: calibre_info.CalibreInfo,
        temp_dir: str,
        site: str,
        path_or_url: str,
        waiting_queue: mp.Queue,
        notification_info: notification_wrapper.NotificationWrapper,
        retry_config: config_models.RetryConfig,
        failure_handler: Callable,
    ) -> bool:
        ff_logging.log_debug(
            f"\t({site}) Using add_format mode - replacing EPUB file only"
        )

        # Get metadata before for comparison
        old_metadata = calibredb_utils.get_metadata(fanfic, cdb)

        # Replace the EPUB format without touching metadata
        success = calibredb_utils.add_format_to_existing_story(temp_dir, fanfic, cdb)

        if not success:
            ff_logging.log_failure(
                f"\t({site}) Failed to replace format for {path_or_url}"
            )
            failure_handler(fanfic, notification_info, waiting_queue, retry_config, cdb)
            return False

        # Get metadata after to verify preservation
        new_metadata = calibredb_utils.get_metadata(fanfic, cdb)
        calibredb_utils.log_metadata_comparison(fanfic, old_metadata, new_metadata)
        return True


class PreserveMetadataStrategy(UpdateStrategy):
    """Strategy for PRESERVE_METADATA mode - export, remove, add, restore."""

    def execute(
        self,
        fanfic: fanfic_info.FanficInfo,
        cdb: calibre_info.CalibreInfo,
        temp_dir: str,
        site: str,
        path_or_url: str,
        waiting_queue: mp.Queue,
        notification_info: notification_wrapper.NotificationWrapper,
        retry_config: config_models.RetryConfig,
        failure_handler: Callable,
    ) -> bool:
        ff_logging.log_debug(
            f"\t({site}) Using preserve_metadata mode - will export and restore metadata fields"
        )

        # Export all metadata before removal
        old_metadata = calibredb_utils.get_metadata(fanfic, cdb)
        if old_metadata:
            restorable_fields = [k for k in old_metadata.keys() if k.startswith("#")]
            ff_logging.log_debug(
                f"\t({site}) Exported {len(restorable_fields)} restorable metadata fields"
            )

        # Remove the existing story
        ff_logging.log(
            f"\t({site}) Removing story {fanfic.calibre_id} from Calibre",
            "OKGREEN",
        )
        calibredb_utils.remove_story(fanfic_info=fanfic, calibre_info=cdb)

        # Add the updated story
        calibredb_utils.add_story(
            location=temp_dir, fanfic_info=fanfic, calibre_info=cdb
        )

        # Verify addition and get new ID
        if not fanfic.get_id_from_calibredb(cdb):
            ff_logging.log_failure(f"\t({site}) Failed to add {path_or_url} to Calibre")
            failure_handler(fanfic, notification_info, waiting_queue, retry_config, cdb)
            return False

        # Restore custom metadata fields
        if old_metadata:
            ff_logging.log_debug(
                f"\t({site}) Restoring metadata to new entry (ID: {fanfic.calibre_id})"
            )
            calibredb_utils.set_metadata_fields(fanfic, cdb, old_metadata)

            # Get final metadata and compare
            new_metadata = calibredb_utils.get_metadata(fanfic, cdb)
            calibredb_utils.log_metadata_comparison(fanfic, old_metadata, new_metadata)

        return True


class RemoveAddStrategy(UpdateStrategy):
    """Strategy for REMOVE_ADD mode - traditional remove and re-add."""

    def execute(
        self,
        fanfic: fanfic_info.FanficInfo,
        cdb: calibre_info.CalibreInfo,
        temp_dir: str,
        site: str,
        path_or_url: str,
        waiting_queue: mp.Queue,
        notification_info: notification_wrapper.NotificationWrapper,
        retry_config: config_models.RetryConfig,
        failure_handler: Callable,
    ) -> bool:
        ff_logging.log_debug(
            f"\t({site}) Using remove_add mode - custom metadata will NOT be preserved"
        )

        # Get metadata before for logging comparison
        old_metadata = calibredb_utils.get_metadata(fanfic, cdb)

        # Remove the existing story
        ff_logging.log(
            f"\t({site}) Removing story {fanfic.calibre_id} from Calibre",
            "OKGREEN",
        )
        calibredb_utils.remove_story(fanfic_info=fanfic, calibre_info=cdb)

        # Add the updated story
        calibredb_utils.add_story(
            location=temp_dir, fanfic_info=fanfic, calibre_info=cdb
        )

        # Verify addition
        if not fanfic.get_id_from_calibredb(cdb):
            ff_logging.log_failure(f"\t({site}) Failed to add {path_or_url} to Calibre")
            failure_handler(fanfic, notification_info, waiting_queue, retry_config, cdb)
            return False

        # Log metadata comparison to show what was lost (debug only)
        new_metadata = calibredb_utils.get_metadata(fanfic, cdb)
        if old_metadata or new_metadata:
            ff_logging.log_debug(f"\t({site}) Metadata comparison (remove_add mode):")
            calibredb_utils.log_metadata_comparison(fanfic, old_metadata, new_metadata)

        return True
