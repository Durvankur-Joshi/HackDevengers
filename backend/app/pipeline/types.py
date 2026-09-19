from enum import Enum
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


class BoundingBox(BaseModel):
    x: int = Field(..., description="Top-left X coordinate in pixels")
    y: int = Field(..., description="Top-left Y coordinate in pixels")
    width: int = Field(..., description="Box width in pixels")
    height: int = Field(..., description="Box height in pixels")


class OCRBlock(BaseModel):
    block_index: int = Field(..., description="0-indexed sequence of text block in reading order")
    text: str = Field(..., description="Extracted textual content")
    confidence: Optional[float] = Field(default=None, description="OCR confidence score (0-100)")
    bbox: BoundingBox = Field(..., description="Pixel bounding box in preprocessed image")
    page_number: int = Field(..., description="1-indexed page number")


class OCRPageResult(BaseModel):
    page_number: int = Field(..., description="1-indexed page number")
    width: int = Field(..., description="Page width in pixels")
    height: int = Field(..., description="Page height in pixels")
    text: str = Field(default="", description="Consolidated page text")
    blocks: List[OCRBlock] = Field(default_factory=list, description="Ordered text blocks on this page")


class OCRMetadata(BaseModel):
    block_count: int = Field(..., description="Total extracted text blocks across all pages")
    average_confidence: Optional[float] = Field(default=None, description="Average OCR confidence across valid blocks")
    processing_duration_ms: Optional[int] = Field(default=None, description="Total execution duration in milliseconds")
    ocr_engine: str = Field(default="tesseract", description="Identifier of the OCR engine used")


class OCRDocumentResult(BaseModel):
    document_id: str = Field(..., description="Document UUID")
    page_count: int = Field(..., description="Total pages processed")
    full_text: str = Field(..., description="Full multi-page document text with page delimiters")
    pages: List[OCRPageResult] = Field(default_factory=list, description="Sequential OCR page results")
    metadata: OCRMetadata = Field(..., description="Document-level OCR metadata and metrics")


class DocumentType(str, Enum):
    INVOICE = "invoice"
    ONBOARDING_FORM = "onboarding_form"
    UNKNOWN = "unknown"


class GeminiClassificationOutput(BaseModel):
    document_type: DocumentType = Field(
        ...,
        description="Classified document archetype: 'invoice', 'onboarding_form', or 'unknown'"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Classification confidence score between 0.0 and 1.0"
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Concise reasons justifying the classification"
    )


class DocumentClassificationResult(BaseModel):
    document_id: str = Field(..., description="Document UUID")
    document_type: DocumentType = Field(..., description="Assigned document classification")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence (0.0 - 1.0)")
    evidence: List[str] = Field(default_factory=list, description="Textual evidence justifying classification")
    ocr_average_confidence: Optional[float] = Field(default=None, description="Average OCR quality confidence")
    classified_at: str = Field(..., description="ISO 8601 classification timestamp")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution and threshold metadata")
