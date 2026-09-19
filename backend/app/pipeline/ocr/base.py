from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from app.pipeline.types import PreprocessedPage, OCRPageResult, OCRDocumentResult


class OCREngineError(Exception):
    """Base exception for OCR engine failures."""
    pass


class OCREngineUnavailableError(OCREngineError):
    """Raised when the OCR engine binary/runtime is not installed or accessible."""
    pass


class BaseOCREngine(ABC):
    """
    Abstract base interface for OCR extraction engines.
    Isolates OCR technology (e.g. Tesseract) from the pipeline and application layers.
    """

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Return the unique name of this OCR engine."""
        pass

    @abstractmethod
    def is_available(self) -> Tuple[bool, Optional[str]]:
        """
        Verify whether the OCR engine is available in the current environment.
        Returns (is_available, error_message_or_path).
        """
        pass

    @abstractmethod
    def extract_page(self, image_path: str, page_number: int) -> OCRPageResult:
        """
        Execute OCR extraction on a single preprocessed page image.
        Returns layout-aware OCRPageResult with bounding boxes, text blocks, and confidence scores.
        """
        pass

    @abstractmethod
    def extract_document(self, document_id: str, pages: List[PreprocessedPage]) -> OCRDocumentResult:
        """
        Sequentially execute OCR extraction on all preprocessed pages of a document.
        Returns a unified OCRDocumentResult with full text, page results, and document metrics.
        """
        pass
