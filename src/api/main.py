"""
Code-Agent — FastAPI Application Entry Point.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.db.session import init_db, close_db
from src.logging_config import setup_logging
from src.api.routes import scan, health, ai, scan_batch

# --- Setup logging before anything else ---
setup_logging(settings.log_level)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown events."""
    # Startup
    logger.info(
        "application_starting",
        service=settings.app_name,
        version=settings.app_version,
        host=settings.api_host,
        port=settings.api_port,
    )
    try:
        await init_db()
        logger.info("database_initialized")
    except Exception as e:
        logger.warning("database_initialization_failed_running_without_db", error=str(e))

    yield

    # Shutdown
    logger.info("application_shutting_down")
    await close_db()


# --- FastAPI App ---
app = FastAPI(
    title=settings.app_name,
    description=(
        "Agente Inteligente para Mapeo y Documentación Automatizada de Arquitectura Técnica. "
        "Analiza repositorios de microservicios, diagnostica calidad de código, "
        "y genera documentación estructurada con IA."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routes ---
app.include_router(health.router)
app.include_router(scan.router)
app.include_router(scan_batch.router)
app.include_router(ai.router)


@app.get("/", include_in_schema=False)
async def root():
    """Root redirect to docs."""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }
