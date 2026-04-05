"""Control API routes — add URLs, trigger actions."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/controls", tags=["controls"])


class AddUrlRequest(BaseModel):
    """Request body for adding a URL to the processing queue."""

    url: str


class AddUrlsRequest(BaseModel):
    """Request body for adding multiple URLs."""

    urls: list[str]


class AddUrlResponse(BaseModel):
    """Response for URL addition."""

    accepted: bool
    message: str


class AddUrlsResponse(BaseModel):
    """Response for batch URL addition."""

    results: list[AddUrlResponse]


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


@router.post("/add-urls", response_model=AddUrlsResponse)
async def add_urls(request: Request, body: AddUrlsRequest):
    """Add multiple fanfiction URLs to the processing queue."""
    state = request.app.state.web_state

    if state.ingress_queue is None:
        return AddUrlsResponse(
            results=[
                AddUrlResponse(accepted=False, message="Ingress queue not available")
                for _ in body.urls
            ]
        )

    from parsers import regex_parsing
    from parsers import auto_url_parsers

    url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
    results = []

    for raw_url in body.urls:
        raw_url = raw_url.strip()
        if not raw_url:
            continue
        try:
            fanfic = regex_parsing.generate_FanficInfo_from_url(raw_url, url_parsers)

            if state.active_urls is not None and fanfic.url in state.active_urls:
                results.append(
                    AddUrlResponse(
                        accepted=False,
                        message=f"Already in queue: {fanfic.url}",
                    )
                )
                continue

            if state.active_urls is not None:
                state.active_urls[fanfic.url] = True

            state.ingress_queue.put(fanfic)
            results.append(
                AddUrlResponse(
                    accepted=True,
                    message=f"Added {fanfic.url} (site: {fanfic.site})",
                )
            )
        except Exception as e:
            results.append(AddUrlResponse(accepted=False, message=f"Error: {e}"))

    return AddUrlsResponse(results=results)
