"""Calibre lookup and metadata extraction service for the web interface."""

import multiprocessing
from typing import Any

from calibre_integration import calibre_info
from calibre_integration import factory as calibre_factory
from models.fanfic_info import FanficInfo


class _LockFactory:
    """CalibreInfo-compatible lock provider without spawning a manager process."""

    @staticmethod
    def Lock():
        return multiprocessing.Lock()


def get_calibre_client(app_state: Any) -> Any | None:
    """Obtain or instantiate CalibreClient if available."""
    client = getattr(app_state, "calibre_client", None)
    if client is not None:
        return client

    web_state = getattr(app_state, "web_state", None)
    if (
        web_state is None
        or web_state.config is None
        or getattr(web_state.config, "calibre", None) is None
        or not getattr(web_state.config.calibre, "location", None)
    ):
        return None

    try:
        cdb_info = calibre_info.CalibreInfo(web_state.config.calibre, _LockFactory())
        return calibre_factory.create_calibre_client(cdb_info, web_state.config_store)
    except Exception:
        return None


def resolve_calibre_book_id(client: Any, query: str) -> str | int | None:
    """Resolve a query (ID, URL, or title) to a Calibre book ID."""
    q = query.strip()
    if not q:
        return None
    if q.isdigit():
        return int(q)
    if "://" in q or q.startswith(("http://", "https://")):
        if hasattr(client, "search_by_url"):
            try:
                res = client.search_by_url(q)
                if res:
                    return res
            except Exception:
                pass
        if hasattr(client, "get_story_id"):
            try:
                fanfic = FanficInfo(url=q, site="unknown")
                res = client.get_story_id(fanfic)
                if res:
                    return res
            except Exception:
                pass
        return None

    # Title substring search
    if hasattr(client, "search_by_title"):
        try:
            res = client.search_by_title(q)
            if res:
                return res
        except Exception:
            pass
    if hasattr(client, "search"):
        try:
            res = client.search(f'title:"{q}"')
            if res:
                return res[0] if isinstance(res, (list, tuple)) else res
        except Exception:
            pass
    if hasattr(client, "_execute_command_with_output"):
        try:
            out = client._execute_command_with_output(["search", f'title:"{q}"'])
            ids = [x.strip() for x in str(out).split(",") if x.strip()]
            if ids:
                return ids[0]
        except Exception:
            pass
    return None


def get_calibre_metadata(
    client: Any, book_id: str | int, url: str
) -> dict[str, object] | None:
    """Fetch metadata for a given Calibre book ID."""
    if hasattr(client, "get_story_metadata"):
        try:
            lookup_id = int(book_id) if str(book_id).isdigit() else book_id
            meta = client.get_story_metadata(lookup_id)
            if meta:
                return dict(meta)
            return None
        except Exception:
            try:
                meta = client.get_story_metadata(str(book_id))
                if meta:
                    return dict(meta)
            except Exception:
                pass
            return None

    if hasattr(client, "get_metadata"):
        try:
            fanfic = FanficInfo(url=url, site="unknown", calibre_id=str(book_id))
            meta = client.get_metadata(fanfic)
            if meta:
                return dict(meta)
        except Exception:
            pass

    return None
