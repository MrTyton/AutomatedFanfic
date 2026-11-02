"""Common worker utility functions for task path resolution."""

from calibre_integration.client_interface import CalibreClient
from calibre_integration.models import BookExport
from models import fanfic_info
from utils import system_utils

__all__ = [
    "get_path_or_url",
]


def get_path_or_url(
    ff_info: fanfic_info.FanficInfo,
    calibre_client: CalibreClient,
    location: str = "",
) -> str:
    """Retrieve the path of an exported story from Calibre or the story's URL if not in Calibre.

    Args:
        ff_info: The fanfic information object.
        calibre_client: The Calibre client.
        location: The directory path to export to.

    Returns:
        The path to the exported story file if it exists in Calibre, or the URL of the story otherwise.
    """
    story_id = calibre_client.get_story_id(ff_info)

    if story_id:
        export_record = calibre_client.export_story(fanfic=ff_info, location=location)
        if isinstance(export_record, BookExport):
            return str(export_record.file_path)

        exported_files = system_utils.get_files(
            location, file_extension=".epub", return_full_path=True
        )
        if exported_files:
            return exported_files[0]

    return ff_info.download_url
