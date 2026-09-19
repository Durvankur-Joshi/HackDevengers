from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class PreprocessedPage(BaseModel):
    page_number: int = Field(..., description="1-indexed sequential page number")
    image_path: str = Field(..., description="Path to the generated OCR-ready image")
    width: int = Field(..., description="Image width in pixels")
    height: int = Field(..., description="Image height in pixels")
    format: str = Field(default="png", description="Image encoding format")
    file_size_bytes: Optional[int] = Field(default=None, description="Image file size in bytes")


class PreprocessingResult(BaseModel):
    document_id: str = Field(..., description="Document UUID")
    original_filename: str = Field(..., description="Original uploaded filename")
    mime_type: str = Field(..., description="Detected MIME type")
    page_count: int = Field(..., description="Total preprocessed pages")
    pages: List[PreprocessedPage] = Field(default_factory=list, description="Ordered OCR-ready pages")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metadata and timing")
    status: str = Field(default="preprocessed", description="Document status after preprocessing")
