"""Unit tests for recording DownloadStatus.PROCESSING in the worker pipeline."""

from unittest.mock import MagicMock, patch

from models.context import WorkerContext
from models.fanfic_info import FanficInfo
from workers import pipeline


def test_url_worker_records_processing_status():
    mock_queue = MagicMock()
    fanfic = FanficInfo(
        url="https://archiveofourown.org/works/999", site="archiveofourown.org"
    )
    mock_queue.empty.side_effect = [False, True]
    mock_queue.get.side_effect = [fanfic, KeyboardInterrupt]

    mock_history_recorder = MagicMock()
    mock_active_urls = {}

    ctx = WorkerContext(
        calibre_client=MagicMock(),
        notification_info=MagicMock(),
        ingress_queue=MagicMock(),
        waiting_queue=MagicMock(),
        retry_config=MagicMock(),
        history_recorder=mock_history_recorder,
        active_urls=mock_active_urls,
    )

    with patch("workers.pipeline._process_task", return_value=True):
        pipeline.url_worker(mock_queue, ctx, "worker_1")

    mock_history_recorder.record_download_processing.assert_called_once_with(
        "https://archiveofourown.org/works/999",
        site="archiveofourown.org",
    )
    assert (
        mock_active_urls.get("https://archiveofourown.org/works/999") is None
        or "https://archiveofourown.org/works/999" not in mock_active_urls
    )
