import os
import time
import shutil
import logging
from typing import List, Tuple, Optional, Dict, Any
from PIL import Image

try:
    import pytesseract
except ImportError:
    pytesseract = None

from app.core.config import settings
from app.pipeline.types import (
    PreprocessedPage,
    BoundingBox,
    OCRBlock,
    OCRPageResult,
    OCRMetadata,
    OCRDocumentResult,
)
from app.pipeline.ocr.base import BaseOCREngine, OCREngineError, OCREngineUnavailableError

logger = logging.getLogger(__name__)

# Standard Windows installation paths for auto-detection
STANDARD_WINDOWS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
local_app_data = os.environ.get("LOCALAPPDATA")
if local_app_data:
    STANDARD_WINDOWS_PATHS.append(os.path.join(local_app_data, r"Programs\Tesseract-OCR\tesseract.exe"))


class TesseractOCREngine(BaseOCREngine):
    """
    Lightweight, layout-aware OCR engine based on Tesseract via pytesseract.
    Preserves text bounding boxes, confidence values, deterministic reading order,
    and constructs consolidated page/document full text.
    """

    def __init__(self):
        self._resolved_cmd: Optional[str] = None
        self._availability_checked = False
        self._is_available = False
        self._availability_message = ""

    @property
    def engine_name(self) -> str:
        return "tesseract"

    def _resolve_tesseract_cmd(self) -> Optional[str]:
        """
        Locate Tesseract executable:
        1. Explicit settings.TESSERACT_CMD if configured.
        2. Standard Windows installation directories.
        3. System PATH fallback via shutil.which('tesseract').
        """
        configured = (settings.TESSERACT_CMD or "").strip()
        if configured:
            # Strip outer quotes if user put quotes in .env
            cleaned = configured.strip('"\'')
            if os.path.isfile(cleaned):
                return cleaned
            logger.warning(f"Configured TESSERACT_CMD '{configured}' was not found on disk.")

        # Check standard Windows paths
        for standard_path in STANDARD_WINDOWS_PATHS:
            if os.path.isfile(standard_path):
                return standard_path

        # Check PATH
        path_which = shutil.which("tesseract") or shutil.which("tesseract.exe")
        if path_which:
            return path_which

        return None

    def is_available(self) -> Tuple[bool, Optional[str]]:
        """
        Check if pytesseract and Tesseract executable are present and functioning.
        """
        if pytesseract is None:
            return False, "pytesseract Python library is not installed in the environment."

        cmd = self._resolve_tesseract_cmd()
        if not cmd:
            return False, "Tesseract executable not found. Please configure TESSERACT_CMD in backend/.env."

        # Configure pytesseract with resolved command
        pytesseract.pytesseract.tesseract_cmd = cmd
        self._resolved_cmd = cmd

        try:
            # Test invocation to confirm binary functions
            version = pytesseract.get_tesseract_version()
            self._is_available = True
            self._availability_message = f"Tesseract {version} available at {cmd}"
            return True, self._availability_message
        except Exception as e:
            self._is_available = False
            self._availability_message = f"Failed to execute Tesseract at {cmd}: {str(e)}"
            return False, self._availability_message

    def extract_page(self, image_path: str, page_number: int) -> OCRPageResult:
        """
        Execute layout-aware OCR extraction on an image page.
        """
        available, error_msg = self.is_available()
        if not available:
            raise OCREngineUnavailableError(
                error_msg or "OCR engine is not available. Please configure TESSERACT_CMD."
            )

        if not os.path.exists(image_path):
            raise OCREngineError(f"Preprocessed page image not found: {image_path}")

        try:
            with Image.open(image_path) as pil_img:
                img_width, img_height = pil_img.size

                # Extract word-level structured tokens with coordinates and confidence
                data = pytesseract.image_to_data(
                    pil_img,
                    output_type=pytesseract.Output.DICT
                )
        except Exception as ocr_err:
            logger.error(f"Tesseract OCR failed on page {page_number} ({image_path}): {ocr_err}")
            raise OCREngineError(f"Tesseract execution error on page {page_number}: {str(ocr_err)}")

        # Group words into lines / blocks by (block_num, par_num, line_num)
        num_items = len(data.get("text", []))
        grouped_lines: Dict[Tuple[int, int, int], List[Dict[str, Any]]] = {}

        for i in range(num_items):
            raw_word = str(data["text"][i]).strip()
            if not raw_word:
                continue

            b_num = data["block_num"][i]
            p_num = data["par_num"][i]
            l_num = data["line_num"][i]
            key = (b_num, p_num, l_num)

            conf_val = data["conf"][i]
            try:
                conf_float = float(conf_val)
                # Tesseract returns -1 for unassigned/header levels
                if conf_float < 0:
                    conf_float = None
            except (ValueError, TypeError):
                conf_float = None

            word_entry = {
                "text": raw_word,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
                "conf": conf_float,
            }

            grouped_lines.setdefault(key, []).append(word_entry)

        # Assemble OCRBlock items from line groups
        raw_blocks: List[OCRBlock] = []

        for _, words in grouped_lines.items():
            if not words:
                continue

            line_text = " ".join(w["text"] for w in words).strip()
            if not line_text:
                continue

            # Compute bounding box encompassing all words in the line
            x = min(w["left"] for w in words)
            y = min(w["top"] for w in words)
            max_r = max(w["left"] + w["width"] for w in words)
            max_b = max(w["top"] + w["height"] for w in words)
            box_w = max(1, max_r - x)
            box_h = max(1, max_b - y)

            # Calculate average confidence for valid words in this block
            valid_confs = [w["conf"] for w in words if w["conf"] is not None]
            line_conf = round(sum(valid_confs) / len(valid_confs), 2) if valid_confs else None

            raw_blocks.append(
                OCRBlock(
                    block_index=0,  # Will be assigned after sorting
                    text=line_text,
                    confidence=line_conf,
                    bbox=BoundingBox(x=x, y=y, width=box_w, height=box_h),
                    page_number=page_number,
                )
            )

        # Deterministic reading order:
        # Sort primarily by page_number, then vertical position (y), then horizontal (x)
        sorted_blocks = sorted(
            raw_blocks,
            key=lambda b: (b.page_number, b.bbox.y, b.bbox.x)
        )

        # Assign 0-indexed sequential block indices
        for idx, block in enumerate(sorted_blocks):
            block.block_index = idx

        # Generate page text from ordered blocks
        page_text = "\n".join(b.text for b in sorted_blocks)

        return OCRPageResult(
            page_number=page_number,
            width=img_width,
            height=img_height,
            text=page_text,
            blocks=sorted_blocks,
        )

    def extract_document(
        self,
        document_id: str,
        pages: List[PreprocessedPage]
    ) -> OCRDocumentResult:
        """
        Execute OCR extraction sequentially across all preprocessed pages of a document.
        """
        start_time = time.time()

        if not pages:
            raise OCREngineError(f"No preprocessed pages provided for document {document_id}.")

        sorted_pages = sorted(pages, key=lambda p: p.page_number)
        page_results: List[OCRPageResult] = []

        for p in sorted_pages:
            page_result = self.extract_page(p.image_path, p.page_number)
            page_results.append(page_result)

        # Generate document full_text with clear page delimiters
        full_text_parts = []
        for pr in page_results:
            full_text_parts.append(f"--- PAGE {pr.page_number} ---")
            if pr.text:
                full_text_parts.append(pr.text)
            else:
                full_text_parts.append("")
        full_text = "\n\n".join(full_text_parts).strip()

        # Compute document-level metrics
        total_blocks = sum(len(pr.blocks) for pr in page_results)

        all_valid_confs: List[float] = []
        for pr in page_results:
            for b in pr.blocks:
                if b.confidence is not None:
                    all_valid_confs.append(b.confidence)

        avg_conf = (
            round(sum(all_valid_confs) / len(all_valid_confs), 2)
            if all_valid_confs
            else None
        )

        duration_ms = round((time.time() - start_time) * 1000)

        metadata = OCRMetadata(
            block_count=total_blocks,
            average_confidence=avg_conf,
            processing_duration_ms=duration_ms,
            ocr_engine=self.engine_name,
        )

        return OCRDocumentResult(
            document_id=document_id,
            page_count=len(page_results),
            full_text=full_text,
            pages=page_results,
            metadata=metadata,
        )
