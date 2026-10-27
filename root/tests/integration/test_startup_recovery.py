"""Integration tests for startup recovery of in-flight and waiting tasks."""

import argparse
import multiprocessing as mp
from unittest.mock import MagicMock, patch

from fanficdownload import register_processes
from history.database import SyncHistoryDB
from history.models import DownloadEvent, DownloadStatus
from models.config_models import (
    AppConfig,
    CalibreConfig,
    EmailConfig,
    RetryConfig,
    WebConfig,
)


def test_startup_recovery_integration(tmp_path):
    db_file = str(tmp_path / "integration_history.db")
    db = SyncHistoryDB(db_file)
    db.connect()

    # Pre-populate SQLite with uncompleted tasks
    db.insert_download(
        DownloadEvent(
            url="https://archiveofourown.org/works/111",
            site="archiveofourown.org",
            title="AO3 Story",
            status=DownloadStatus.PENDING,
        )
    )
    db.insert_download(
        DownloadEvent(
            url="https://www.fanfiction.net/s/222",
            site="fanfiction.net",
            title="FFNet Story",
            status=DownloadStatus.PROCESSING,
        )
    )
    db.insert_download(
        DownloadEvent(
            url="https://www.royalroad.com/fiction/333",
            site="royalroad.com",
            title="RoyalRoad Story",
            status=DownloadStatus.WAITING,
        )
    )
    db.close()

    config = AppConfig(
        email=EmailConfig(
            email="test@example.com",
            password="pass",
            server="imap.example.com",
            mailbox="INBOX",
        ),
        calibre=CalibreConfig(path=str(tmp_path)),
        retry=RetryConfig(resume_uncompleted_on_startup=True),
        web=WebConfig(enabled=False, history_db_path=db_file),
    )

    args = argparse.Namespace(config="dummy.toml", verbose=False)
    mock_pm = MagicMock()

    with mp.Manager() as manager:
        with patch("fanficdownload.calibre_factory.create_calibre_client"):
            register_processes(
                process_manager=mock_pm,
                config=config,
                args=args,
                manager=manager,
                url_parsers={},
            )

        assert mock_pm.register_process.called
        supervisor_call = [
            c
            for c in mock_pm.register_process.call_args_list
            if c.args[0] == "supervisor"
        ]
        assert len(supervisor_call) == 1
        ipc = supervisor_call[0].kwargs["args"][0]

        # Verify ingress_queue contains the 3 recovered stories
        assert ipc.ingress_queue.qsize() == 3

        recovered_items = []
        while not ipc.ingress_queue.empty():
            recovered_items.append(ipc.ingress_queue.get_nowait())

        urls = {item.url for item in recovered_items}
        assert urls == {
            "https://archiveofourown.org/works/111",
            "https://www.fanfiction.net/s/222",
            "https://www.royalroad.com/fiction/333",
        }
        for item in recovered_items:
            assert item.repeats == 0

        # Verify active_urls contains all 3 entries as queued
        assert (
            ipc.active_urls["https://archiveofourown.org/works/111"]["status"]
            == "queued"
        )
        assert ipc.active_urls["https://www.fanfiction.net/s/222"]["status"] == "queued"
        assert (
            ipc.active_urls["https://www.royalroad.com/fiction/333"]["status"]
            == "queued"
        )

    if hasattr(mock_pm, "_history_writer") and mock_pm._history_writer:
        mock_pm._history_writer.stop()


def test_startup_recovery_disabled_integration(tmp_path):
    db_file = str(tmp_path / "integration_history_disabled.db")
    db = SyncHistoryDB(db_file)
    db.connect()
    db.insert_download(
        DownloadEvent(
            url="https://archiveofourown.org/works/999",
            site="archiveofourown.org",
            status=DownloadStatus.PENDING,
        )
    )
    db.close()

    config = AppConfig(
        email=EmailConfig(
            email="test@example.com",
            password="pass",
            server="imap.example.com",
            mailbox="INBOX",
        ),
        calibre=CalibreConfig(path=str(tmp_path)),
        retry=RetryConfig(resume_uncompleted_on_startup=False),
        web=WebConfig(enabled=False, history_db_path=db_file),
    )

    args = argparse.Namespace(config="dummy.toml", verbose=False)
    mock_pm = MagicMock()

    with mp.Manager() as manager:
        with patch("fanficdownload.calibre_factory.create_calibre_client"):
            register_processes(
                process_manager=mock_pm,
                config=config,
                args=args,
                manager=manager,
                url_parsers={},
            )

        supervisor_call = [
            c
            for c in mock_pm.register_process.call_args_list
            if c.args[0] == "supervisor"
        ]
        ipc = supervisor_call[0].kwargs["args"][0]

        # Verify queue is empty because recovery is disabled
        assert ipc.ingress_queue.qsize() == 0
        assert len(ipc.active_urls) == 0

    if hasattr(mock_pm, "_history_writer") and mock_pm._history_writer:
        mock_pm._history_writer.stop()
