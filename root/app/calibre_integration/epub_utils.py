"""EPUB file inspection, title extraction, and metadata diagnostics for Calibre integration."""

import zipfile
from xml.etree import ElementTree as ET

import ff_logging


def extract_title_from_epub_path(epub_path: str) -> str:
    """Extract the story title from an EPUB file path.

    Args:
        epub_path: Path to the EPUB file, which may contain the story title.

    Returns:
        Extracted title, or the original path if extraction fails.
    """
    try:
        if epub_path.lower().endswith(".epub"):
            filename = epub_path.replace("\\", "/").split("/")[-1]
            return filename[:-5]
        return epub_path
    except Exception as e:
        ff_logging.log_debug(f"Failed to extract title from path {epub_path}: {e}")
        return epub_path


def log_epub_metadata(epub_path: str, site: str) -> None:
    """Read and log metadata from an EPUB file to diagnose FanFicFare issues.

    Extracts key metadata fields from the EPUB container that FanFicFare uses
    to determine the source URL and story details.

    Args:
        epub_path: Path to the EPUB file.
        site: Site identifier for logging context.
    """
    try:
        with zipfile.ZipFile(epub_path, "r") as zip_ref:
            container_xml = zip_ref.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            ns = {"u": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile_elem = container_root.find(".//u:rootfile", ns)
            if rootfile_elem is None:
                raise ValueError("Could not find rootfile element in container.xml")
            rootfile_path = rootfile_elem.attrib["full-path"]

            opf_xml = zip_ref.read(rootfile_path)
            opf_root = ET.fromstring(opf_xml)

            metadata: dict[str, str | None] = {}
            for elem in opf_root.iter():
                tag_lower = elem.tag.lower()
                if "identifier" in tag_lower:
                    metadata[f"Identifier ({elem.attrib.get('id', 'unknown')})"] = (
                        elem.text
                    )
                elif "source" in tag_lower:
                    metadata["Source"] = elem.text
                elif "description" in tag_lower:
                    desc = elem.text or ""
                    metadata["Description"] = (
                        (desc[:50] + "...") if len(desc) > 50 else desc
                    )

            ff_logging.log_debug(f"\t({site}) Metadata check for {epub_path}:")
            for key, value in metadata.items():
                ff_logging.log_debug(f"\t\t{key}: {value}")

    except Exception as e:
        ff_logging.log_debug(f"\t({site}) Error reading epub metadata: {e}")
