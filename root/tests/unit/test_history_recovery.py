"""Unit tests for startup history recovery."""

import queue
from unittest.mock import MagicMock, patch

from history.database import SyncHistoryDB
from history.models import DownloadEvent, DownloadStatus
from history.recovery import recover_uncompleted_downloads


def test_recover_uncompleted_downloads_success(tmp_path):
    db_file = str(tmp_path / "test_history.db")
    db = SyncHistoryDB(db_file)
    db.connect()

    # 1. Pending download
    db.insert_download(
        DownloadEvent(
            url="https://example.com/pending_1",
            site="ao3",
            title="Pending Story",
            calibre_id="101",
            behavior="update",
            status=DownloadStatus.PENDING,
        )
    )

    # 2. Interrupted download (processing)
    db.insert_download(
        DownloadEvent(
            url="https://example.com/processing_2",
            site="ffnet",
            title="Processing Story",
            calibre_id="102",
            behavior="force",
            status=DownloadStatus.PROCESSING,
        )
    )

    # 3. Waiting retry
    db.insert_download(
        DownloadEvent(
            url="https://example.com/waiting_3",
            site="royalroad",
            title="Waiting Story",
            calibre_id="103",
            behavior=None,
            status=DownloadStatus.WAITING,
        )
    )

    # 4. Completed download (should be ignored)
    db.insert_download(
        DownloadEvent(
            url="https://example.com/completed_4",
            site="ao3",
            title="Completed Story",
            status=DownloadStatus.SUCCESS,
        )
    )
    db.close()

    ingress_q = queue.Queue()
    active_urls = {}
    mock_recorder = MagicMock()

    count = recover_uncompleted_downloads(
        history_db_path=db_file,
        ingress_queue=ingress_q,
        active_urls=active_urls,
        history_recorder=mock_recorder,
    )

    assert count == 3
    assert ingress_q.qsize() == 3

    # Check recovered items from queue
    items = [ingress_q.get_nowait() for _ in range(3)]
    item_urls = {item.url: item for item in items}

    assert "https://example.com/pending_1" in item_urls
    assert "https://example.com/processing_2" in item_urls
    assert "https://example.com/waiting_3" in item_urls
    assert "https://example.com/completed_4" not in item_urls

    # Check that repeats are reset to 0 (fresh attempts)
    for item in items:
        assert item.repeats == 0

    # Check behavior and attributes preserved
    assert item_urls["https://example.com/processing_2"].behavior == "force"
    assert item_urls["https://example.com/pending_1"].calibre_id == "101"

    # Check active_urls entries
    assert active_urls["https://example.com/pending_1"]["status"] == "queued"
    assert active_urls["https://example.com/processing_2"]["status"] == "queued"
    assert active_urls["https://example.com/waiting_3"]["status"] == "queued"

    # Check recorder calls
    assert mock_recorder.record_download_requeued.call_count == 3
    call_args_list = mock_recorder.record_download_requeued.call_args_list

    # Verify interrupted download received specific message
    interrupted_call = [
        c
        for c in call_args_list
        if c.kwargs.get("url") == "https://example.com/processing_2"
    ]
    assert len(interrupted_call) == 1
    assert "Interrupted during active download" in interrupted_call[0].kwargs.get(
        "error_message"
    )


def test_recover_uncompleted_downloads_missing_db(tmp_path):
    missing_file = str(tmp_path / "nonexistent.db")
    ingress_q = queue.Queue()
    active_urls = {}

    count = recover_uncompleted_downloads(
        history_db_path=missing_file,
        ingress_queue=ingress_q,
        active_urls=active_urls,
        history_recorder=None,
    )

    assert count == 0
    assert ingress_q.empty()
    assert len(active_urls) == 0


def test_recover_uncompleted_downloads_empty_db(tmp_path):
    db_file = str(tmp_path / "empty.db")
    db = SyncHistoryDB(db_file)
    db.connect()
    db.close()

    ingress_q = queue.Queue()
    active_urls = {}

    count = recover_uncompleted_downloads(
        history_db_path=db_file,
        ingress_queue=ingress_q,
        active_urls=active_urls,
        history_recorder=None,
    )

    assert count == 0
    assert ingress_q.empty()
    assert len(active_urls) == 0


def test_recover_uncompleted_downloads_database_exception(tmp_path):
    db_file = str(tmp_path / "corrupt.db")
    with open(db_file, "w") as f:
        f.write("not an sqlite database")

    ingress_q = queue.Queue()
    active_urls = {}

    with patch("history.recovery.ff_logging.log_failure") as mock_log_fail:
        count = recover_uncompleted_downloads(
            history_db_path=db_file,
            ingress_queue=ingress_q,
            active_urls=active_urls,
            history_recorder=None,
        )

    assert count == 0
    mock_log_fail.assert_called_once()


def test_recover_uncompleted_downloads_ignores_cancelled_and_scheme_variants(tmp_path):
    db_file = str(tmp_path / "test_history.db")
    db = SyncHistoryDB(db_file)
    db.connect()

    # Waiting attempt (without scheme, as created by worker/ingester)
    db.insert_download(
        DownloadEvent(
            url="royalroad.com/fiction/100326",
            site="royalroad",
            title="Into the Unown",
            status=DownloadStatus.WAITING,
        )
    )

    # User cancels it (update or separate record with scheme)
    db.update_download(
        url="https://royalroad.com/fiction/100326",
        status=DownloadStatus.ABANDONED,
    )
    db.close()

    ingress_q = queue.Queue()
    active_urls = {}

    count = recover_uncompleted_downloads(
        history_db_path=db_file,
        ingress_queue=ingress_q,
        active_urls=active_urls,
        history_recorder=None,
    )

    assert count == 0
    assert ingress_q.empty()
    assert len(active_urls) == 0
