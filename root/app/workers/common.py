"""
Common utility functions for worker modules.
"""

import zipfile
from xml.etree import ElementTree as ET
import ff_logging
import fanfic_info
import calibredb_utils

import system_utils


def get_path_or_url(
    ff_info: fanfic_info.FanficInfo,
    calibre_client: calibredb_utils.CalibreDBClient,
    location: str = "",
) -> str:
    """
    Retrieves the path of an exported story from the Calibre library or the story's
    URL if not in Calibre.

    Args:
        ff_info (fanfic_info.FanficInfo): The fanfic information object.
        calibre_client (calibredb_utils.CalibreDBClient): The Calibre DB client.
        location (str, optional): The directory path to export to.

    Returns:
        str: The path to the exported story file if it exists in Calibre, or the
            URL of the story otherwise.
    """
    # Check if the story exists in the Calibre library by attempting to retrieve its ID
    if calibre_client.get_story_id(ff_info):
        # Export the story to the specified location
        calibre_client.export_story(fanfic=ff_info, location=location)
        # Assuming export_story function successfully exports the story, retrieve and return the path to the exported file
        exported_files = system_utils.get_files(
            location, file_extension=".epub", return_full_path=True
        )
        # Check if the list is not empty
        if exported_files:
            # Return the first file path found
            return exported_files[0]

    # If the story does not exist in the Calibre library or no files were exported, return the URL of the story
    return ff_info.url


def extract_title_from_epub_path(epub_path: str) -> str:
    """
    Extract the story title from an epub file path.

    Args:
        epub_path (str): Path to the epub file, which may contain the story title

    Returns:
        str: Extracted title, or the original path if extraction fails
    """
    try:
        if epub_path.lower().endswith(".epub"):
            # Handle both Windows and Linux path separators
            filename = epub_path.split("\\")[-1].split("/")[-1]
            return filename[:-5]

        return epub_path
    except Exception as e:
        ff_logging.log_debug(f"Failed to extract title from path {epub_path}: {e}")
        return epub_path


def log_epub_metadata(epub_path: str, site: str) -> None:
    """
    Read and log the metadata from an epub file to help diagnose FanFicFare issues.

    This function extracts key metadata fields from the epub that FanFicFare uses
    to determine the source URL and other story details. This is crucial for
    debugging cases where FanFicFare can't find the source URL.

    Args:
        epub_path (str): Path to the epub file
        site (str): Site identifier for logging context
    """
    try:
        with zipfile.ZipFile(epub_path, "r") as zip_ref:
            # Find content.opf file
            container_xml = zip_ref.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            # Namespace for container.xml
            ns = {"u": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile_path = container_root.find(".//u:rootfile", ns).attrib["full-path"]

            # Read content.opf
            opf_xml = zip_ref.read(rootfile_path)
            # Remove namespace prefixes effectively for simple parsing or just use namespaces
            # A simple approach for logging:
            opf_root = ET.fromstring(opf_xml)

            # Namespaces likely in OPF
            # Common ones: dc: http://purl.org/dc/elements/1.1/
            # opf: http://www.idpf.org/2007/opf

            metadata = {}
            # Extract anything that looks like a source URL or identifier
            for elem in opf_root.iter():
                # Check for dc:identifier
                if "identifier" in elem.tag.lower():
                    metadata[
                        f"Identifier ({elem.attrib.get('id', 'unknown')})"
                    ] = elem.text
                # Check for dc:source
                if "source" in elem.tag.lower():
                    metadata["Source"] = elem.text
                # Check for description
                if "description" in elem.tag.lower():
                    # Truncate description
                    desc = elem.text if elem.text else ""
                    metadata["Description"] = (
                        (desc[:50] + "...") if len(desc) > 50 else desc
                    )

            ff_logging.log_debug(f"\t({site}) Metadata check for {epub_path}:")
            for key, value in metadata.items():
                ff_logging.log_debug(f"\t\t{key}: {value}")

    except Exception as e:
        ff_logging.log_debug(f"\t({site}) Error reading epub metadata: {e}")
