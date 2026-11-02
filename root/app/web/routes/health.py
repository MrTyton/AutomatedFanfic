"""Health and status API routes."""

from fastapi import APIRouter, Request

from web.services import diagnostics_service

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


@router.get("/version")
async def system_version(request: Request) -> dict[str, object]:
    """Return runtime environment and component versions for diagnostics and error reporting."""
    return diagnostics_service.get_system_version_payload(request.app.state)


@router.get("/status")
async def system_status(request: Request):
    """Overall system status including process states and queue sizes."""
    return diagnostics_service.get_system_status_payload(request.app.state.web_state)
