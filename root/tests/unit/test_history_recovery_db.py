"""Unit tests for history recovery database queries and DownloadStatus.PROCESSING."""

import pytest

from history.database import AsyncHistoryDB, SyncHistoryDB
from history.models import DownloadEvent, DownloadStatus


@pytest.fixture
def sync_db(tmp_path):
    db_file = str(tmp_path / "test_history.db")
    db = SyncHistoryDB(db_file)
    db.connect()
    yield db
    db.close()


@pytest.fixture
def async_db(tmp_path):
    db_file = str(tmp_path / "test_history_async.db")
    # Initialize schema with sync db first
    sync_init = SyncHistoryDB(db_file)
    sync_init.connect()
    sync_init.close()
    return AsyncHistoryDB(db_file)


def test_download_status_processing_enum():
    assert DownloadStatus.PROCESSING == "processing"
    assert DownloadStatus.PROCESSING.value == "processing"


def test_update_download_to_processing(sync_db):
    event = DownloadEvent(
        url="https://example.com/story1",
        site="ao3",
        title="Original Title",
        status=DownloadStatus.PENDING,
    )
    sync_db.insert_download(event)

    # Update to processing
    sync_db.update_download(
        url="https://example.com/story1",
        status=DownloadStatus.PROCESSING,
        site="ao3",
    )

    rows = sync_db.get_uncompleted_downloads()
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/story1"
    assert rows[0]["status"] == "processing"


def test_get_uncompleted_downloads_filtering(sync_db):
    # Pending
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/pending",
            site="ao3",
            title="Pending Story",
            status=DownloadStatus.PENDING,
        )
    )

    # Processing
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/processing",
            site="ffnet",
            title="Processing Story",
            status=DownloadStatus.PROCESSING,
        )
    )

    # Waiting
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/waiting",
            site="royalroad",
            title="Waiting Story",
            status=DownloadStatus.WAITING,
        )
    )

    # Success
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/success",
            site="ao3",
            title="Success Story",
            status=DownloadStatus.SUCCESS,
        )
    )

    # Failed
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/failed",
            site="ao3",
            title="Failed Story",
            status=DownloadStatus.FAILED,
        )
    )

    # Abandoned
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/abandoned",
            site="ao3",
            title="Abandoned Story",
            status=DownloadStatus.ABANDONED,
        )
    )

    uncompleted = sync_db.get_uncompleted_downloads()
    uncompleted_urls = {row["url"] for row in uncompleted}

    assert uncompleted_urls == {
        "https://example.com/pending",
        "https://example.com/processing",
        "https://example.com/waiting",
    }
    assert "https://example.com/success" not in uncompleted_urls
    assert "https://example.com/failed" not in uncompleted_urls
    assert "https://example.com/abandoned" not in uncompleted_urls


def test_get_uncompleted_downloads_deduplication(sync_db):
    # Story was pending, then updated to success
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/story_completed",
            site="ao3",
            status=DownloadStatus.PENDING,
        )
    )
    sync_db.update_download(
        url="https://example.com/story_completed",
        status=DownloadStatus.SUCCESS,
    )

    # Story was pending, then updated to waiting
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/story_retrying",
            site="ffnet",
            status=DownloadStatus.PENDING,
        )
    )
    sync_db.update_download(
        url="https://example.com/story_retrying",
        status=DownloadStatus.WAITING,
        error_message="Rate limit 429",
    )

    uncompleted = sync_db.get_uncompleted_downloads()
    assert len(uncompleted) == 1
    assert uncompleted[0]["url"] == "https://example.com/story_retrying"
    assert uncompleted[0]["status"] == "waiting"
    assert uncompleted[0]["error_message"] == "Rate limit 429"


@pytest.mark.anyio
async def test_async_get_uncompleted_downloads(async_db):
    sync_db = SyncHistoryDB(async_db._db_path)
    sync_db.connect()
    sync_db.insert_download(
        DownloadEvent(
            url="https://example.com/async_uncompleted",
            site="ao3",
            title="Async Title",
            status=DownloadStatus.PROCESSING,
        )
    )
    sync_db.close()

    rows = await async_db.get_uncompleted_downloads()
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/async_uncompleted"
    assert rows[0]["status"] == "processing"
    assert rows[0]["title"] == "Async Title"
    await async_db.close()
