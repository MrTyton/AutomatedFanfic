"""Unit tests for models/active_urls.py and web/routes/controls.py helpers."""

from queue import Queue
from unittest.mock import MagicMock

import pytest

from models import active_urls
from models.active_urls import ActiveUrlEntry
from models.fanfic_info import FanficInfo


class TestActiveUrlsHelpers:
    """Tests for models.active_urls helper functions."""

    def test_is_url_active_handles_empty_missing_and_cancelled(self):
        # Empty store — no URLs are active
        assert active_urls.is_url_active({}, "https://example.com/1") is False

        store: dict[str, ActiveUrlEntry] = {
            "https://example.com/1": {"site": "example", "status": "queued"},
            "https://example.com/2": {"site": "example", "status": "cancelled"},
        }
        assert active_urls.is_url_active(store, "https://example.com/1") is True
        assert active_urls.is_url_active(store, "https://example.com/2") is False
        assert active_urls.is_url_active(store, "https://example.com/3") is False

    def test_mark_url_queued_fresh_and_merge_modes(self):
        store: dict[str, ActiveUrlEntry] = {
            "https://example.com/1": {
                "site": "example",
                "status": "waiting",
                "heap_gen": 7,
            }
        }
        # Fresh write (merge=False) drops old keys like heap_gen
        active_urls.mark_url_queued(
            store,
            "https://example.com/1",
            site="example",
            title="Story 1",
            calibre_id="42",
        )
        assert store["https://example.com/1"] == {
            "site": "example",
            "title": "Story 1",
            "status": "queued",
            "calibre_id": "42",
        }

        # Merge mode preserves existing keys and supports pop_keys / behavior
        store["https://example.com/2"] = {
            "site": "ao3",
            "title": "Story 2",
            "status": "processing",
            "heap_gen": 9,
        }
        active_urls.mark_url_queued(
            store,
            "https://example.com/2",
            behavior="force",
            merge=True,
            pop_keys=("heap_gen",),
        )
        assert store["https://example.com/2"] == {
            "site": "ao3",
            "title": "Story 2",
            "status": "queued",
            "behavior": "force",
        }

    def test_mark_url_processing_and_update_url_title(self):
        store: dict[str, ActiveUrlEntry] = {
            "https://example.com/1": {"status": "queued", "heap_gen": 3}
        }
        active_urls.mark_url_processing(store, "https://example.com/1", site="ao3")
        assert store["https://example.com/1"] == {
            "site": "ao3",
            "status": "processing",
            "heap_gen": 3,
        }

        active_urls.update_url_title(
            store,
            "https://example.com/1",
            title="Extracted Title",
            site="ao3",
        )
        assert store["https://example.com/1"] == {
            "site": "ao3",
            "title": "Extracted Title",
            "status": "processing",
            "heap_gen": 3,
        }

    def test_mark_url_waiting_respects_cancelled_and_delete_if_cancelled(self):
        store: dict[str, ActiveUrlEntry] = {
            "https://example.com/active": {"site": "ao3", "status": "processing"},
            "https://example.com/cancelled": {"site": "ao3", "status": "cancelled"},
        }
        ok = active_urls.mark_url_waiting(
            store,
            "https://example.com/active",
            site="ao3",
            title="My Fic",
            calibre_id="100",
            heap_gen=5,
        )
        assert ok is True
        assert store["https://example.com/active"] == {
            "site": "ao3",
            "title": "My Fic",
            "calibre_id": "100",
            "status": "waiting",
            "heap_gen": 5,
        }

        # Cancelled without delete_if_cancelled leaves it untouched and returns False
        ok_cancel_keep = active_urls.mark_url_waiting(
            store,
            "https://example.com/cancelled",
            site="ao3",
            delete_if_cancelled=False,
        )
        assert ok_cancel_keep is False
        assert "https://example.com/cancelled" in store

        # Cancelled with delete_if_cancelled removes it and returns False
        ok_cancel_del = active_urls.mark_url_waiting(
            store,
            "https://example.com/cancelled",
            site="ao3",
            delete_if_cancelled=True,
        )
        assert ok_cancel_del is False
        assert "https://example.com/cancelled" not in store

    def test_mark_url_failed_and_mark_url_cancelled_and_remove_active_url(self):
        store: dict[str, ActiveUrlEntry] = {
            "https://example.com/series": {"site": "ao3", "status": "queued"}
        }
        active_urls.mark_url_failed(
            store, "https://example.com/series", "403 Forbidden"
        )
        assert store["https://example.com/series"] == {
            "site": "ao3",
            "status": "failed",
            "error": "403 Forbidden",
        }

        was_changed = active_urls.mark_url_cancelled(
            store, "https://example.com/series"
        )
        assert was_changed is True
        assert store["https://example.com/series"]["status"] == "cancelled"
        assert (
            active_urls.mark_url_cancelled(store, "https://example.com/series") is False
        )

        active_urls.remove_active_url(store, "https://example.com/series")
        assert "https://example.com/series" not in store

    def test_get_queue_depths_supported_and_unsupported(self):
        ingress_q = Queue()
        ingress_q.put(FanficInfo(url="https://example.com/1", site="ao3"))
        waiting_q = Queue()
        worker_q = Queue()
        worker_q.put(FanficInfo(url="https://example.com/2", site="ao3"))
        worker_q.put(FanficInfo(url="https://example.com/3", site="ao3"))

        depths = active_urls.get_queue_depths(
            ingress_q, waiting_q, {"worker_0": worker_q}
        )
        assert depths == {
            "ingress": 1,
            "waiting": 0,
            "workers": {"worker_0": 2},
        }

        broken_q = MagicMock()
        broken_q.qsize.side_effect = NotImplementedError()
        depths_fallback = active_urls.get_queue_depths(
            broken_q, None, {"worker_0": broken_q}
        )
        assert depths_fallback == {
            "ingress": -1,
            "workers": {"worker_0": -1},
        }


class TestControlsHelpers:
    """Tests for extracted helpers in web.routes.controls."""

    def test_dequeue_from_all_queues_removes_matching_across_waiting_ingress_and_workers(
        self,
    ):
        from web.routes import controls

        waiting_q = Queue()
        ingress_q = Queue()
        worker_q = Queue()

        target = "https://archiveofourown.org/works/111"
        keep = "https://archiveofourown.org/works/222"

        waiting_q.put(FanficInfo(url=target, site="ao3"))
        waiting_q.put(FanficInfo(url=keep, site="ao3"))
        ingress_q.put(FanficInfo(url=target, site="ao3"))
        worker_q.put(FanficInfo(url=target, site="ao3"))
        worker_q.put(FanficInfo(url=keep, site="ao3"))

        state = MagicMock()
        state.waiting_queue = waiting_q
        state.ingress_queue = ingress_q
        state.worker_queues = {"worker_0": worker_q}

        w_rem, i_rem, wk_rem = controls._dequeue_from_all_queues(state, [target])
        assert len(w_rem) == 1 and w_rem[0].url == target
        assert len(i_rem) == 1 and i_rem[0].url == target
        assert len(wk_rem) == 1 and wk_rem[0].url == target
        assert waiting_q.qsize() == 1
        assert ingress_q.qsize() == 0
        assert worker_q.qsize() == 1

    @pytest.mark.anyio
    async def test_resolve_candidate_urls_combines_metadata_and_canonical_url(self):
        from unittest.mock import AsyncMock, patch
        from web.routes import controls

        state = MagicMock()
        state.history_db = MagicMock()
        state.history_db.get_latest_download = AsyncMock(
            return_value={
                "site": "archiveofourown.org",
                "title": "History Title",
                "calibre_id": "77",
            }
        )
        body = controls.QueueActionRequest(
            url="archiveofourown.org/works/12345/chapters/67890"
        )

        with patch(
            "web.routes.controls._build_fanfic",
            return_value=FanficInfo(
                url="https://archiveofourown.org/works/12345",
                site="archiveofourown.org",
                title="History Title",
            ),
        ):
            (
                raw_url,
                canonical_url,
                candidates,
                canonical_fanfic,
                site,
                title,
                calibre_id,
            ) = await controls._resolve_candidate_urls(state, body)

        assert raw_url == "https://archiveofourown.org/works/12345/chapters/67890"
        assert canonical_url == "https://archiveofourown.org/works/12345"
        assert candidates == [
            "https://archiveofourown.org/works/12345",
            "https://archiveofourown.org/works/12345/chapters/67890",
        ]
        assert canonical_fanfic is not None
        assert site == "archiveofourown.org"
        assert title == "History Title"
        assert calibre_id == "77"

    def test_ingest_single_url_enqueues_and_deduplicates(self):
        from web.routes import controls

        state = MagicMock()
        state.ingress_queue = Queue()
        state.active_urls = {}
        state.history_recorder = MagicMock()

        resp1 = controls._ingest_single_url(
            state,
            "https://archiveofourown.org/works/999",
            {},
            duplicate_prefix="URL already in queue",
            added_suffix=" to processing queue",
        )
        assert resp1.accepted is True
        assert state.ingress_queue.qsize() == 1
        assert (
            state.active_urls["https://archiveofourown.org/works/999"]["status"]
            == "queued"
        )
        state.history_recorder.record_download_created.assert_called_once()

        # Second call for same URL is rejected as duplicate
        resp2 = controls._ingest_single_url(
            state,
            "https://archiveofourown.org/works/999",
            {},
            duplicate_prefix="URL already in queue",
            added_suffix=" to processing queue",
        )
        assert resp2.accepted is False
        assert "URL already in queue" in resp2.message
        assert state.ingress_queue.qsize() == 1
