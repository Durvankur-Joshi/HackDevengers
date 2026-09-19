from fastapi import APIRouter
from app.schemas import HealthResponse, SystemInfoResponse
from app.core.config import settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Health check endpoint to verify backend service availability."""
    return HealthResponse(status="ok")


@router.get("/", response_model=SystemInfoResponse, tags=["System"])
async def root() -> SystemInfoResponse:
    """Root info endpoint providing basic service status."""
    return SystemInfoResponse(
        name=settings.PROJECT_NAME,
        version=settings.VERSION,
        status="running",
        environment=settings.ENVIRONMENT
    )
