from app.pipeline.ocr.base import BaseOCREngine, OCREngineError, OCREngineUnavailableError
from app.pipeline.ocr.engine import TesseractOCREngine

# Default singleton instance
_default_engine = None


def get_ocr_engine() -> BaseOCREngine:
    """Factory to retrieve the configured OCR engine instance."""
    global _default_engine
    if _default_engine is None:
        _default_engine = TesseractOCREngine()
    return _default_engine


__all__ = [
    "BaseOCREngine",
    "TesseractOCREngine",
    "OCREngineError",
    "OCREngineUnavailableError",
    "get_ocr_engine",
]
