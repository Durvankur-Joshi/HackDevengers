from fastapi import APIRouter
from app.schemas import HealthResponse, DatabaseHealthResponse, SystemInfoResponse
from app.core.config import settings
from app.services.supabase import supabase_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Health check endpoint to verify backend service availability."""
    return HealthResponse(status="ok")


@router.get("/health/db", response_model=DatabaseHealthResponse, tags=["Health"])
async def database_health_check() -> DatabaseHealthResponse:
    """
    Database health check endpoint to verify Supabase PostgreSQL availability.
    Communicates strictly through the Supabase service abstraction layer.
    """
    result = supabase_service.check_connection()
    return DatabaseHealthResponse(
        status=result.get("status", "error"),
        database=result.get("database", "disconnected"),
        message=result.get("message")
    )


@router.get("/", response_model=SystemInfoResponse, tags=["System"])
async def root() -> SystemInfoResponse:
    """Root info endpoint providing basic service status."""
    return SystemInfoResponse(
        name=settings.PROJECT_NAME,
        version=settings.VERSION,
        status="running",
        environment=settings.ENVIRONMENT
    )
