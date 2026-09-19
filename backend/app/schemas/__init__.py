from typing import Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(default="ok", example="ok")


class DatabaseHealthResponse(BaseModel):
    status: str = Field(..., example="ok")
    database: str = Field(..., example="connected")
    message: Optional[str] = Field(default=None)


class SystemInfoResponse(BaseModel):
    name: str
    version: str
    status: str
    environment: str


class DocumentResponse(BaseModel):
    id: str
    filename: str
    document_type: Optional[str] = "unknown"
    status: str = "uploaded"
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    storage_path: Optional[str] = None
    summary: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    preview_url: Optional[str] = None


class DocumentPreviewResponse(BaseModel):
    document_id: str
    filename: str
    preview_url: str
    expires_in: int = 3600
