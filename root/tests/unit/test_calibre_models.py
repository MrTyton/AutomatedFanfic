from pathlib import Path
import pytest

from calibre_integration.models import (
    AddedBook,
    BookExport,
    CalibreAuthError,
    CalibreConfigurationError,
    CalibreConnectionError,
    CalibreError,
    CalibreOperationError,
    MetadataUpdateReport,
)


def test_book_export_dataclass() -> None:
    export = BookExport(
        file_path=Path("/tmp/book.epub"), format="EPUB", size_bytes=1024
    )
    assert export.file_path == Path("/tmp/book.epub")
    assert export.format == "EPUB"
    assert export.size_bytes == 1024


def test_added_book_dataclass() -> None:
    added = AddedBook(calibre_id="42", title="Sample Story", formats=("EPUB",))
    assert added.calibre_id == "42"
    assert added.title == "Sample Story"
    assert added.formats == ("EPUB",)
    with pytest.raises(TypeError):
        AddedBook(calibre_id="42")  # type: ignore[call-arg]


def test_metadata_update_report() -> None:
    report = MetadataUpdateReport(updated_fields=("#words", "#genre"), failed_fields=())
    assert report.is_success is True

    failed_report = MetadataUpdateReport(
        updated_fields=("#words",), failed_fields=("#bad",)
    )
    assert failed_report.is_success is False


def test_calibre_exceptions() -> None:
    assert issubclass(CalibreConnectionError, CalibreError)
    assert issubclass(CalibreAuthError, CalibreError)
    assert issubclass(CalibreConfigurationError, CalibreError)
    assert issubclass(CalibreOperationError, CalibreError)
    assert issubclass(CalibreError, OSError)
