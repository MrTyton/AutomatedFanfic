"""Startup recovery for in-flight, waiting, and interrupted fanfiction downloads.

Scans the SQLite history database during application startup to rehydrate uncompleted
tasks (status in 'pending', 'processing', 'waiting') into active memory queues,
resuming them as fresh attempts.
"""

from pathlib import Path

from history.database import SyncHistoryDB
from history.recorder import HistoryRecorder
from models import active_urls as active_urls_utils
from models.active_urls import ActiveUrlsDict
from models.fanfic_info import FanficInfo
from models.queue_types import IngressQueue
from utils import ff_logging


def recover_uncompleted_downloads(
    history_db_path: str,
    ingress_queue: IngressQueue,
    active_urls: ActiveUrlsDict,
    history_recorder: HistoryRecorder | None,
) -> int:
    """Scan history.db and rehydrate uncompleted tasks into active_urls and ingress_queue.

    Args:
        history_db_path: Path to the SQLite history database file.
        ingress_queue: Task ingress queue to populate with recovered FanficInfo objects.
        active_urls: Shared active_urls dict to mark recovered items as 'queued'.
        history_recorder: HistoryRecorder facade to audit requeued status, or None.

    Returns:
        int: Total number of recovered downloads re-enqueued.
    """
    if not history_db_path or not Path(history_db_path).exists():
        ff_logging.log_debug(
            f"History recovery: Database '{history_db_path}' not found or empty, skipping recovery."
        )
        return 0

    try:
        db = SyncHistoryDB(history_db_path)
        db.connect()
        try:
            uncompleted = db.get_uncompleted_downloads()
        finally:
            db.close()
    except Exception as exc:
        ff_logging.log_failure(
            f"History recovery: Failed to query uncompleted downloads from '{history_db_path}': {exc}"
        )
        return 0

    if not uncompleted:
        ff_logging.log_debug("History recovery: No uncompleted downloads found.")
        return 0

    recovered_count = 0
    interrupted_count = 0

    for row in uncompleted:
        url = row["url"]
        site = row.get("site") or ""
        title = row.get("title")
        calibre_id = row.get("calibre_id")
        behavior = row.get("behavior")
        status = row.get("status")

        is_interrupted = status == "processing"
        if is_interrupted:
            interrupted_count += 1
            ff_logging.log(
                f"History recovery: Resuming interrupted download for {url} as a fresh attempt"
            )
            requeue_msg = "Interrupted during active download by container restart; restarted as fresh attempt"
        else:
            ff_logging.log(
                f"History recovery: Re-queueing uncompleted download for {url}"
            )
            requeue_msg = "Re-queued on application startup"

        fanfic = FanficInfo(
            url=url,
            site=site,
            calibre_id=calibre_id,
            repeats=0,
            behavior=behavior,
            title=title,
        )

        active_urls_utils.mark_url_queued(
            active_urls,
            fanfic.url,
            site=fanfic.site,
            title=fanfic.title,
            calibre_id=fanfic.calibre_id,
            behavior=fanfic.behavior,
        )

        ingress_queue.put(fanfic)

        if history_recorder is not None:
            history_recorder.record_download_requeued(
                url=fanfic.url,
                site=fanfic.site,
                title=fanfic.title,
                error_message=requeue_msg,
            )

        recovered_count += 1

    ff_logging.log(
        f"History recovery: Successfully re-queued {recovered_count} uncompleted downloads "
        f"({interrupted_count} interrupted mid-download)."
    )
    return recovered_count
