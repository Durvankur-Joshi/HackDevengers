"""Document processing pipeline modules."""
from app.pipeline.types import (
    PreprocessedPage,
    PreprocessingResult,
    BoundingBox,
    OCRBlock,
    OCRPageResult,
    OCRMetadata,
    OCRDocumentResult,
    DocumentType,
    GeminiClassificationOutput,
    DocumentClassificationResult,
)
from app.pipeline.preprocessing import preprocess_document
from app.pipeline.ocr import (
    BaseOCREngine,
    TesseractOCREngine,
    OCREngineError,
    OCREngineUnavailableError,
    get_ocr_engine,
)
from app.pipeline.classifier import DocumentClassifier, classify_document

__all__ = [
    "PreprocessedPage",
    "PreprocessingResult",
    "preprocess_document",
    "BoundingBox",
    "OCRBlock",
    "OCRPageResult",
    "OCRMetadata",
    "OCRDocumentResult",
    "DocumentType",
    "GeminiClassificationOutput",
    "DocumentClassificationResult",
    "BaseOCREngine",
    "TesseractOCREngine",
    "OCREngineError",
    "OCREngineUnavailableError",
    "get_ocr_engine",
    "DocumentClassifier",
    "classify_document",
]
