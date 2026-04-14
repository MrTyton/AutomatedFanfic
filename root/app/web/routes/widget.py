"""Widget API route — flat JSON for Homepage (gethomepage.dev) integration."""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["widget"])


@router.get("/widget")
async def homepage_widget(request: Request):
    """Single flat JSON endpoint for Homepage customapi widget.

    Returns summary stats (block display) and active items list
    (dynamic-list display) in one response so two Homepage widget
    configs can point at the same URL.
    """
    state = request.app.state.web_state

    # Build set of URLs currently in retry backoff
    waiting_urls: set[str] = set()
    if state.history_db is not None:
        try:
            for row in await state.history_db.get_waiting_urls():
                waiting_urls.add(row["url"])
        except Exception:
            pass

    # Active downloads
    active_items = []
    active_count = 0
    if state.active_urls is not None:
        try:
            for url, meta in state.active_urls.items():
                entry = {"url": url}
                if isinstance(meta, dict):
                    entry["site"] = meta.get("site", "unknown")
                    entry["title"] = meta.get("title", url)
                else:
                    entry["site"] = "unknown"
                    entry["title"] = url
                entry["state"] = "waiting" if url in waiting_urls else "downloading"
                active_items.append(entry)
            active_count = len(active_items)
        except Exception:
            pass

    # Ingress queue depth
    queued = 0
    if state.ingress_queue is not None:
        try:
            queued = state.ingress_queue.qsize()
        except NotImplementedError:
            queued = 0

    # Waiting/retry queue depth
    waiting_retry = 0
    if state.waiting_queue is not None:
        try:
            waiting_retry = state.waiting_queue.qsize()
        except NotImplementedError:
            waiting_retry = 0

    # Total completed downloads from history DB
    total_completed = 0
    if state.history_db is not None:
        try:
            total_completed = await state.history_db.get_download_count(
                status="success"
            )
        except Exception:
            total_completed = 0

    return {
        "active_downloads": active_count,
        "queued": queued,
        "waiting_retry": waiting_retry,
        "total_completed": total_completed,
        "status": "running",
        "active": active_items,
    }
