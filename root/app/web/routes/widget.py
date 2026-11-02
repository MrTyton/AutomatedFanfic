"""Widget API route — flat JSON for Homepage (gethomepage.dev) integration."""

from fastapi import APIRouter, Request

from web.services.dashboard_snapshot import build_homepage_widget

router = APIRouter(prefix="/api", tags=["widget"])


@router.get("/widget")
async def homepage_widget(request: Request):
    """Single flat JSON endpoint for Homepage customapi widget.

    Returns summary stats (block display) and active items list
    (dynamic-list display) in one response so two Homepage widget
    configs can point at the same URL.
    """
    return await build_homepage_widget(request.app.state.web_state)
