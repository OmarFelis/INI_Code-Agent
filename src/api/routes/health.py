"""
Code-Agent — Health check route.
GET /health — Returns service health status including database connectivity.
"""

import structlog
from fastapi import APIRouter
from sqlalchemy import text

from src.api.schemas.scan_response import HealthResponse
from src.config import settings
from src.db.session import async_session_factory

logger = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service health status and database connectivity.",
)
async def health_check():
    """Check service health and database connectivity."""
    db_status = "disconnected"

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            db_status = "connected"
    except Exception as e:
        logger.warning("health_check_db_failed", error=str(e))
        db_status = f"error: {type(e).__name__}"

    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        database=db_status,
    )
