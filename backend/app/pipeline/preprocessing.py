import os
import io
import time
import shutil
import logging
from typing import Optional, Dict, Any, List
from PIL import Image, ImageOps, ImageEnhance
import fitz  # PyMuPDF

from app.pipeline.types import PreprocessedPage, PreprocessingResult
from app.services.supabase import supabase_service
from app.services.storage import storage_service

logger = logging.getLogger(__name__)

# Base temporary directory for preprocessed page images
BASE_TMP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../tmp/processing"))
MAX_IMAGE_DIMENSION = 2400
PDF_RENDER_DPI = 200


def _ensure_clean_dir(target_dir: str) -> None:
    """Ensure directory exists and is empty for idempotent processing runs."""
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
    os.makedirs(target_dir, exist_ok=True)


def _normalize_image(img: Image.Image) -> Image.Image:
    """
    Normalize orientation, color space, dimensions, and contrast for OCR readiness.
    """
    # 1. Orientation correction from EXIF
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # 2. Color mode normalization (handle transparency over white background)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # 3. Reasonable dimension constraint (avoid excessive memory while maintaining OCR resolution)
    width, height = img.size
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

    # 4. Light contrast enhancement to clarify faint text/scans
    try:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.15)
    except Exception:
        pass

    return img


def preprocess_pdf(file_bytes: bytes, output_dir: str) -> List[PreprocessedPage]:
    """
    Convert all pages of a PDF into ordered, OCR-ready PNG page images.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Corrupted or invalid PDF file: {str(e)}")

    page_count = len(doc)
    if page_count == 0:
        raise ValueError("PDF document contains no readable pages.")

    pages: List[PreprocessedPage] = []

    for page_idx in range(page_count):
        page = doc[page_idx]
        # Render at 200 DPI for optimal OCR balance
        pix = page.get_pixmap(dpi=PDF_RENDER_DPI)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Apply standard normalization
        img = _normalize_image(img)

        page_num = page_idx + 1
        page_filename = f"page_{page_num:03d}.png"
        out_path = os.path.join(output_dir, page_filename)
        img.save(out_path, format="PNG", optimize=True)

        pages.append(
            PreprocessedPage(
                page_number=page_num,
                image_path=out_path,
                width=img.width,
                height=img.height,
                format="png",
                file_size_bytes=os.path.getsize(out_path)
            )
        )

    doc.close()
    return pages


def preprocess_image(file_bytes: bytes, output_dir: str) -> List[PreprocessedPage]:
    """
    Process a single image (JPG, PNG) into an OCR-ready PNG page.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()
    except Exception as e:
        raise ValueError(f"Unreadable or corrupted image file: {str(e)}")

    img = _normalize_image(img)

    page_filename = "page_001.png"
    out_path = os.path.join(output_dir, page_filename)
    img.save(out_path, format="PNG", optimize=True)

    return [
        PreprocessedPage(
            page_number=1,
            image_path=out_path,
            width=img.width,
            height=img.height,
            format="png",
            file_size_bytes=os.path.getsize(out_path)
        )
    ]


def preprocess_document(document_id: str) -> PreprocessingResult:
    """
    Main preprocessing entry point:
    1. Retrieve metadata from PostgreSQL.
    2. Set status to 'preprocessing' and record start log.
    3. Download binary document from Supabase Storage.
    4. Render/normalize pages into temporary directory.
    5. Record completion log and update status to 'preprocessed'.
    """
    start_time = time.time()

    # 1. Fetch document record
    doc = supabase_service.get_document(document_id)
    if not doc:
        raise ValueError(f"Document with ID '{document_id}' not found.")

    storage_path = doc.get("storage_path")
    filename = doc.get("filename", f"doc_{document_id}")
    mime_type = (doc.get("mime_type") or "").lower()

    if not storage_path:
        raise ValueError(f"Document '{document_id}' has no associated storage path.")

    # 2. Update status to 'preprocessing' and write log
    try:
        supabase_service.update_document_status(document_id, "preprocessing")
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="preprocessing",
            status="started",
            message="Document preprocessing started"
        )
    except Exception as e:
        logger.warning(f"Failed to update document status to 'preprocessing': {e}")

    # 3. Download binary from Storage
    try:
        file_bytes = storage_service.download_file(storage_path)
    except Exception as e:
        # Mark as failed
        err_msg = f"Failed to retrieve document binary from storage: {str(e)}"
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="preprocessing",
                status="failed",
                message=err_msg
            )
        except Exception:
            pass
        raise RuntimeError(err_msg)

    # 4. Setup clean temporary directory
    target_dir = os.path.join(BASE_TMP_DIR, document_id)
    _ensure_clean_dir(target_dir)

    # 5. Process according to format
    is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")

    try:
        if is_pdf:
            pages = preprocess_pdf(file_bytes, target_dir)
        else:
            pages = preprocess_image(file_bytes, target_dir)
    except Exception as proc_err:
        err_msg = f"Preprocessing failed: {str(proc_err)}"
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="preprocessing",
                status="failed",
                message=err_msg
            )
        except Exception:
            pass
        raise RuntimeError(err_msg)

    duration_ms = round((time.time() - start_time) * 1000)

    # 6. Record success in database & logs
    try:
        supabase_service.update_document_status(document_id, "preprocessed")
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="preprocessing",
            status="completed",
            message="Document preprocessing completed successfully",
            metadata={
                "page_count": len(pages),
                "duration_ms": duration_ms,
                "mime_type": mime_type,
                "is_pdf": is_pdf
            }
        )
    except Exception as e:
        logger.warning(f"Failed to record completion log for document '{document_id}': {e}")

    return PreprocessingResult(
        document_id=document_id,
        original_filename=filename,
        mime_type=mime_type or ("application/pdf" if is_pdf else "image/png"),
        page_count=len(pages),
        pages=pages,
        metadata={
            "processing_duration_ms": duration_ms,
            "render_dpi": PDF_RENDER_DPI if is_pdf else None,
            "output_directory": target_dir
        },
        status="preprocessed"
    )
