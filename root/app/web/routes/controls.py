"""Control API routes — add URLs, trigger actions."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/controls", tags=["controls"])


class AddUrlRequest(BaseModel):
    """Request body for adding a URL to the processing queue."""

    url: str


class AddUrlResponse(BaseModel):
    """Response for URL addition."""

    accepted: bool
    message: str


@router.post("/add-url", response_model=AddUrlResponse)
async def add_url(request: Request, body: AddUrlRequest):
    """Add a fanfiction URL directly to the ingress queue."""
    state = request.app.state.web_state

    if state.ingress_queue is None:
        return AddUrlResponse(accepted=False, message="Ingress queue not available")

    from parsers import regex_parsing
    from parsers import auto_url_parsers

    # Parse the URL to create a FanficInfo
    url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
    fanfic = regex_parsing.generate_FanficInfo_from_url(body.url, url_parsers)

    # Check for duplicates
    if state.active_urls is not None and fanfic.url in state.active_urls:
        return AddUrlResponse(
            accepted=False, message=f"URL already in queue: {fanfic.url}"
        )

    # Add to active_urls and queue
    if state.active_urls is not None:
        state.active_urls[fanfic.url] = True

    state.ingress_queue.put(fanfic)

    return AddUrlResponse(
        accepted=True,
        message=f"Added {fanfic.url} (site: {fanfic.site}) to processing queue",
    )
