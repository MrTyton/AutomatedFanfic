"""Stats API route — aggregated statistics for the Stats dashboard page."""

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
async def get_stats(
    request: Request,
    period: str = Query("24h", pattern="^(24h|7d|30d)$"),
):
    """Return aggregated stats for the stats dashboard page.

    Query param `period`: "24h", "7d", or "30d" (default "24h").
    """
    period_map = {"24h": 24, "7d": 168, "30d": 720}
    period_hours = period_map.get(period, 24)

    state = request.app.state.web_state

    if state.history_db is None:
        return {"error": "History database not available", "period": period}

    try:
        stats = await state.history_db.get_stats(period_hours=period_hours)
        return {"period": period, **stats}
    except Exception:
        return {"error": "Failed to fetch stats", "period": period}
