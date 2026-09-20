import os
import re
import uuid
import logging
import glob
import json
import time
from typing import Optional, List
from PIL import Image
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from app.schemas import DocumentResponse, DocumentPreviewResponse
from app.pipeline.types import (
    PreprocessingResult,
    OCRDocumentResult,
    PreprocessedPage,
    DocumentClassificationResult,
    DocumentSection,
    DocumentSectionResult,
    ExtractedField,
    DocumentExtractionResult,
    DocumentValidationSummary,
    DocumentValidationResult,
)
from app.pipeline.ocr import get_ocr_engine, OCREngineUnavailableError, OCREngineError
from app.pipeline.classifier import classify_document
from app.pipeline.section_detector import detect_sections_for_document
from app.pipeline.extractor import extract_document_fields
from app.pipeline.validator import DocumentValidator
from app.pipeline.preprocessing import BASE_TMP_DIR
from app.services.supabase import supabase_service
from app.services.storage import storage_service
from app.services.gemini import gemini_service, GeminiServiceError, GeminiNotConfiguredError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["Documents"])

MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/jpg",
}

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
}


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal and special character injection."""
    base_name = os.path.basename(filename.strip())
    # Keep alphanumeric, dot, underscore, dash
    clean_name = re.sub(r"[^a-zA-Z0-9._-]", "_", base_name)
    return clean_name or f"document_{uuid.uuid4().hex[:8]}"


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
    """
    Ingest a document:
    1. Validate MIME type and file extension.
    2. Validate file size (<= 10MB).
    3. Generate document UUID and safe storage path.
    4. Store metadata in PostgreSQL.
    5. Store binary payload in Supabase Storage.
    6. Record processing log entry.
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided or filename is missing."
        )

    # Validate file extension
    _, ext = os.path.splitext(file.filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not supported. Please upload a PDF, JPG, or PNG."
        )

    # Validate MIME type
    content_type = (file.content_type or "").lower()
    if content_type == "image/jpg":
        content_type = "image/jpeg"

    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not supported. Please upload a PDF, JPG, or PNG."
        )

    # Read binary content
    try:
        content = await file.read()
    except Exception as e:
        logger.error(f"Error reading uploaded file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read uploaded file content."
        )

    # Validate size
    file_size = len(content)
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty."
        )

    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is too large. Maximum size is {MAX_FILE_SIZE_MB} MB."
        )

    # Generate document UUID and safe storage path
    doc_id = str(uuid.uuid4())
    safe_name = sanitize_filename(file.filename)
    storage_path = f"documents/{doc_id}/{safe_name}"

    # Verify Supabase configuration
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured. Please check backend/.env credentials."
        )

    # 1. Create document metadata record in PostgreSQL with status 'uploaded'
    try:
        inserted = supabase_service.insert_document(
            filename=file.filename,
            document_id=doc_id,
            document_type="unknown",
            status="uploaded",
            mime_type=content_type,
            file_size=file_size,
            storage_path=storage_path
        )
    except Exception as e:
        logger.error(f"Failed to record document metadata in PostgreSQL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error while recording document: {str(e)}"
        )

    # 2. Upload file to Supabase Storage
    try:
        storage_service.upload_file(
            file_bytes=content,
            storage_path=storage_path,
            mime_type=content_type
        )
    except Exception as e:
        logger.error(f"Failed to upload document to Supabase Storage: {e}")
        # Roll back / mark document status as failed in database
        try:
            supabase_service.update_document_status(doc_id, "failed")
            supabase_service.create_processing_log(
                document_id=doc_id,
                stage="upload",
                status="failed",
                message=f"Storage upload failed: {str(e)}"
            )
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload failed while saving to storage. Please try again."
        )

    # 3. Record successful processing log
    try:
        supabase_service.create_processing_log(
            document_id=doc_id,
            stage="upload",
            status="completed",
            message="Document uploaded successfully",
            metadata={
                "original_filename": file.filename,
                "mime_type": content_type,
                "file_size": file_size,
                "storage_path": storage_path,
            }
        )
    except Exception as log_err:
        logger.warning(f"Failed to write processing log for document {doc_id}: {log_err}")

    # Generate preview signed URL
    preview_url = storage_service.create_signed_url(storage_path, expires_in=3600)

    return DocumentResponse(
        id=doc_id,
        filename=inserted.get("filename", file.filename),
        document_type=inserted.get("document_type", "unknown"),
        status=inserted.get("status", "uploaded"),
        mime_type=inserted.get("mime_type", content_type),
        file_size=inserted.get("file_size", file_size),
        storage_path=storage_path,
        summary=inserted.get("summary"),
        created_at=str(inserted.get("created_at") or ""),
        updated_at=str(inserted.get("updated_at") or ""),
        preview_url=preview_url
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str) -> DocumentResponse:
    """Retrieve document metadata by UUID, including preview access."""
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    storage_path = doc.get("storage_path")
    preview_url = None
    if storage_path:
        preview_url = storage_service.create_signed_url(storage_path, expires_in=3600)

    return DocumentResponse(
        id=str(doc.get("id")),
        filename=doc.get("filename"),
        document_type=doc.get("document_type", "unknown"),
        status=doc.get("status", "uploaded"),
        mime_type=doc.get("mime_type"),
        file_size=doc.get("file_size"),
        storage_path=storage_path,
        summary=doc.get("summary"),
        created_at=str(doc.get("created_at") or ""),
        updated_at=str(doc.get("updated_at") or ""),
        preview_url=preview_url
    )


@router.get("/{document_id}/preview", response_model=DocumentPreviewResponse)
async def get_document_preview(document_id: str) -> DocumentPreviewResponse:
    """Generate a temporary signed URL to view/download the original document."""
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    storage_path = doc.get("storage_path")
    if not storage_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No storage path associated with this document."
        )

    signed_url = storage_service.create_signed_url(storage_path, expires_in=3600)
    if not signed_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate signed preview URL for this document."
        )

    return DocumentPreviewResponse(
        document_id=document_id,
        filename=doc.get("filename"),
        preview_url=signed_url,
        expires_in=3600
    )


@router.post("/{document_id}/preprocess", response_model=PreprocessingResult)
async def preprocess_document_endpoint(document_id: str) -> PreprocessingResult:
    """
    Execute document preprocessing stage:
    1. Retrieve binary document from storage.
    2. Convert PDF pages to 200 DPI images or normalize image orientation/contrast.
    3. Save OCR-ready page files in clean temporary processing directory.
    4. Update document status to 'preprocessed' and write audit logs.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    # Check document existence
    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    try:
        from app.pipeline import preprocess_document
        result = preprocess_document(document_id)
        return result
    except ValueError as val_err:
        logger.warning(f"Validation error during preprocessing of {document_id}: {val_err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )
    except Exception as err:
        logger.error(f"Preprocessing error on document {document_id}: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Preprocessing failed: {str(err)}"
        )


@router.post("/{document_id}/ocr", response_model=OCRDocumentResult)
async def ocr_document_endpoint(document_id: str) -> OCRDocumentResult:
    """
    Execute OCR extraction stage:
    1. Validate document existence in PostgreSQL.
    2. Verify OCR-ready preprocessed page images exist.
    3. Check OCR engine availability (Tesseract).
    4. Transition status to 'ocr' and record start audit log.
    5. Execute layout-aware OCR extraction across all pages.
    6. Persist structured result artifact to backend/tmp/processing/{document_id}/ocr.json.
    7. Update status to 'ocr_completed' and record completion log.
    8. Return complete OCRDocumentResult.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    # 1. Validate document existence
    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    # 2. Verify preprocessing output exists
    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))
    if not os.path.exists(target_dir):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document must be preprocessed before OCR."
        )

    page_files = sorted(glob.glob(os.path.join(target_dir, "page_*.png")))
    if not page_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document must be preprocessed before OCR. No page images found."
        )

    # Load OCR-ready pages
    pages: List[PreprocessedPage] = []
    for idx, p_path in enumerate(page_files):
        match = re.search(r"page_(\d+)\.png", os.path.basename(p_path))
        page_num = int(match.group(1)) if match else (idx + 1)
        try:
            with Image.open(p_path) as p_img:
                w, h = p_img.size
        except Exception:
            w, h = 0, 0

        pages.append(
            PreprocessedPage(
                page_number=page_num,
                image_path=p_path,
                width=w,
                height=h,
                format="png",
                file_size_bytes=os.path.getsize(p_path) if os.path.exists(p_path) else None,
            )
        )

    # 3. Check OCR engine availability
    engine = get_ocr_engine()
    available, error_msg = engine.is_available()
    if not available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_msg or "OCR engine is not available. Please configure TESSERACT_CMD."
        )

    # 4. Update status to 'ocr' and record audit log
    try:
        supabase_service.update_document_status(document_id, "ocr")
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="ocr",
            status="started",
            message="OCR extraction started",
            metadata={"page_count": len(pages)}
        )
    except Exception as log_err:
        logger.warning(f"Failed to record OCR started log for {document_id}: {log_err}")

    # 5. Run OCR extraction
    try:
        ocr_result = engine.extract_document(document_id=document_id, pages=pages)
    except OCREngineUnavailableError as unavail_err:
        logger.error(f"OCR engine unavailable during processing of {document_id}: {unavail_err}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="ocr",
                status="failed",
                message=str(unavail_err)
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(unavail_err)
        )
    except Exception as proc_err:
        err_msg = f"OCR processing failed: {str(proc_err)}"
        logger.error(f"OCR execution error for {document_id}: {err_msg}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="ocr",
                status="failed",
                message=err_msg
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=err_msg
        )

    # 6. Save structured OCR JSON artifact
    ocr_json_path = os.path.join(target_dir, "ocr.json")
    try:
        with open(ocr_json_path, "w", encoding="utf-8") as f:
            f.write(ocr_result.model_dump_json(indent=2))
    except Exception as save_err:
        logger.warning(f"Failed to write ocr.json artifact for {document_id}: {save_err}")

    # 7. Update status to 'ocr_completed' & record completion log
    try:
        supabase_service.update_document_status(document_id, "ocr_completed")
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="ocr",
            status="completed",
            message="OCR extraction completed successfully",
            metadata={
                "page_count": ocr_result.page_count,
                "block_count": ocr_result.metadata.block_count,
                "average_confidence": ocr_result.metadata.average_confidence,
                "processing_duration_ms": ocr_result.metadata.processing_duration_ms,
            }
        )
    except Exception as log_err:
        logger.warning(f"Failed to record OCR completion log for {document_id}: {log_err}")

    return ocr_result


@router.get("/{document_id}/ocr", response_model=OCRDocumentResult)
async def get_document_ocr_endpoint(document_id: str) -> OCRDocumentResult:
    """
    Retrieve structured OCR result artifact for an existing document if already processed.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))
    ocr_json_path = os.path.join(target_dir, "ocr.json")

    if not os.path.isfile(ocr_json_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OCR result not found for document '{document_id}'. Run POST /api/documents/{document_id}/ocr first."
        )

    try:
        with open(ocr_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return OCRDocumentResult.model_validate(data)
    except Exception as err:
        logger.error(f"Failed to read ocr.json for {document_id}: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse stored OCR result: {str(err)}"
        )


@router.post("/{document_id}/classify", response_model=DocumentClassificationResult)
async def classify_document_endpoint(document_id: str) -> DocumentClassificationResult:
    """
    Execute document classification stage:
    1. Validate document exists in PostgreSQL database.
    2. Verify OCR output artifact (ocr.json) exists.
    3. Verify Gemini API service configuration.
    4. Transition status to 'classified' and record start audit log.
    5. Execute semantic classification via Gemini using structured OCR input.
    6. Persist classification result artifact to backend/tmp/processing/{document_id}/classification.json.
    7. Update documents.document_type and documents.status in PostgreSQL.
    8. Record completion audit log with metrics.
    9. Return DocumentClassificationResult.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    # 1. Validate document existence
    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    # 2. Verify OCR has been completed
    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))
    ocr_json_path = os.path.join(target_dir, "ocr.json")

    if not os.path.isfile(ocr_json_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document must be processed with OCR before classification."
        )

    try:
        with open(ocr_json_path, "r", encoding="utf-8") as f:
            ocr_data = json.load(f)
        ocr_result = OCRDocumentResult.model_validate(ocr_data)
    except Exception as read_err:
        logger.error(f"Failed to load OCR result for {document_id}: {read_err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stored OCR result is invalid or corrupted. Please re-run OCR."
        )

    # 3. Check Gemini configuration
    if not gemini_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API key is not configured. Please set GEMINI_API_KEY in backend/.env."
        )

    # 4. Record audit start log
    try:
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="classification",
            status="started",
            message="Document classification started",
            metadata={"page_count": ocr_result.page_count}
        )
    except Exception as log_err:
        logger.warning(f"Failed to record classification start log for {document_id}: {log_err}")

    # 5. Execute classification
    try:
        classification_res = classify_document(ocr_result)
    except GeminiNotConfiguredError as cfg_err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(cfg_err)
        )
    except GeminiServiceError as gem_err:
        err_msg = f"AI classification failed: {str(gem_err)}"
        logger.error(f"Gemini classification error for {document_id}: {err_msg}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="classification",
                status="failed",
                message=err_msg
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=err_msg
        )
    except Exception as general_err:
        err_msg = f"Classification processing error: {str(general_err)}"
        logger.error(f"Unexpected error classifying {document_id}: {err_msg}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="classification",
                status="failed",
                message=err_msg
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during classification. Please check server logs."
        )

    # 6. Save classification JSON artifact
    classification_json_path = os.path.join(target_dir, "classification.json")
    try:
        with open(classification_json_path, "w", encoding="utf-8") as f:
            f.write(classification_res.model_dump_json(indent=2))
    except Exception as save_err:
        logger.warning(f"Failed to write classification.json for {document_id}: {save_err}")

    # 7. Update documents table in PostgreSQL: document_type & status='classified'
    try:
        supabase_service.update_document_status(
            document_id=document_id,
            status="classified",
            document_type=classification_res.document_type.value
        )
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="classification",
            status="completed",
            message="Document classification completed successfully",
            metadata={
                "document_type": classification_res.document_type.value,
                "confidence": classification_res.confidence,
                "ocr_average_confidence": classification_res.ocr_average_confidence,
                "confidence_threshold": classification_res.metadata.get("confidence_threshold"),
                "below_threshold": classification_res.metadata.get("below_threshold"),
            }
        )
    except Exception as db_err:
        logger.warning(f"Failed to persist classification status to DB for {document_id}: {db_err}")

    return classification_res


@router.get("/{document_id}/classification", response_model=DocumentClassificationResult)
async def get_document_classification_endpoint(document_id: str) -> DocumentClassificationResult:
    """
    Retrieve stored classification result artifact for an existing document.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))
    classification_json_path = os.path.join(target_dir, "classification.json")

    if not os.path.isfile(classification_json_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Classification result not found for document '{document_id}'. Run POST /api/documents/{document_id}/classify first."
        )

    try:
        with open(classification_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return DocumentClassificationResult.model_validate(data)
    except Exception as err:
        logger.error(f"Failed to read classification.json for {document_id}: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse stored classification result: {str(err)}"
        )


# ==============================================================================
# Phase 7 — Section Detection Endpoints
# ==============================================================================

@router.post("/{document_id}/detect-sections", response_model=DocumentSectionResult)
async def detect_document_sections_endpoint(document_id: str) -> DocumentSectionResult:
    """
    Execute Phase 7 logical section detection:
    1. Validate document exists and is accessible.
    2. Ensure OCR result exists (ocr.json).
    3. Ensure classification result exists (classification.json or document_type in DB).
    4. If document_type == 'unknown', returns empty sections [] without calling Gemini.
    5. Invoke SectionDetector with structure-only prompt.
    6. Validate section names against supported whitelists.
    7. Persist detected sections in Supabase document_sections table.
    8. Update document status to 'sectioned' and create audit logs.
    9. Return DocumentSectionResult.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured. Please set SUPABASE credentials."
        )

    # 1. Fetch document record
    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))

    # 2. Check OCR precondition
    ocr_json_path = os.path.join(target_dir, "ocr.json")
    if not os.path.isfile(ocr_json_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OCR has not been run for document '{document_id}'. Run POST /api/documents/{document_id}/ocr first."
        )

    try:
        with open(ocr_json_path, "r", encoding="utf-8") as f:
            ocr_data = json.load(f)
        ocr_result = OCRDocumentResult.model_validate(ocr_data)
    except Exception as err:
        logger.error(f"Failed to read ocr.json for {document_id}: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load OCR data: {str(err)}"
        )

    # 3. Check Classification precondition
    classification_json_path = os.path.join(target_dir, "classification.json")
    classification_type = "unknown"

    if os.path.isfile(classification_json_path):
        try:
            with open(classification_json_path, "r", encoding="utf-8") as f:
                class_data = json.load(f)
            classification_type = class_data.get("document_type", "unknown")
        except Exception:
            classification_type = doc.get("document_type") or "unknown"
    elif doc.get("document_type"):
        classification_type = doc.get("document_type")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document '{document_id}' has not been classified yet. Run POST /api/documents/{document_id}/classify first."
        )

    # 4. Record audit log: started
    try:
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="section_detection",
            status="started",
            message="Section detection started",
            metadata={"document_type": classification_type}
        )
    except Exception as log_err:
        logger.warning(f"Failed to record section detection started log for {document_id}: {log_err}")

    # 5. Run Section Detection
    try:
        section_result = detect_sections_for_document(ocr_result, classification_type)
    except GeminiNotConfiguredError as cfg_err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(cfg_err)
        )
    except GeminiServiceError as gem_err:
        err_msg = f"AI section detection failed: {str(gem_err)}"
        logger.error(f"Gemini section detection error for {document_id}: {err_msg}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="section_detection",
                status="failed",
                message=err_msg
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=err_msg
        )
    except Exception as general_err:
        err_msg = f"Section detection processing error: {str(general_err)}"
        logger.error(f"Unexpected error detecting sections for {document_id}: {err_msg}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="section_detection",
                status="failed",
                message=err_msg
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during section detection. Please check server logs."
        )

    # 6. Save detected sections in Supabase document_sections table
    try:
        supabase_service.insert_document_sections(document_id, section_result.sections)
    except Exception as db_sec_err:
        logger.warning(f"Failed to insert sections into document_sections table for {document_id}: {db_sec_err}")

    # 7. Update documents table in PostgreSQL: status='sectioned'
    try:
        supabase_service.update_document_status(
            document_id=document_id,
            status="sectioned"
        )
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="section_detection",
            status="completed",
            message="Section detection completed successfully",
            metadata={
                "section_count": len(section_result.sections),
                "document_type": section_result.document_type,
            }
        )
    except Exception as db_err:
        logger.warning(f"Failed to update document status to sectioned for {document_id}: {db_err}")

    return section_result


@router.get("/{document_id}/sections", response_model=DocumentSectionResult)
async def get_document_sections_endpoint(document_id: str) -> DocumentSectionResult:
    """
    Retrieve stored section detection results for an existing document.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))
    sections_json_path = os.path.join(target_dir, "sections.json")

    if os.path.isfile(sections_json_path):
        try:
            with open(sections_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return DocumentSectionResult.model_validate(data)
        except Exception as err:
            logger.error(f"Failed to read sections.json for {document_id}: {err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to parse stored sections: {str(err)}"
            )

    # Fallback to database query if artifact not on local disk
    db_sections = supabase_service.get_document_sections(document_id)
    if db_sections:
        sections_list = [
            DocumentSection(
                section_id=s.get("id") or str(uuid.uuid4()),
                document_id=document_id,
                section_name=s.get("section_name", "unknown"),
                page_number=s.get("page_number", 1),
                text=s.get("raw_text", ""),
                confidence=float(s.get("confidence", 0.0) or 0.0),
                block_ids=[],
                bbox=None,
            )
            for s in db_sections
        ]
        return DocumentSectionResult(
            document_id=document_id,
            document_type=doc.get("document_type") or "unknown",
            sections=sections_list,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Section detection result not found for document '{document_id}'. Run POST /api/documents/{document_id}/detect-sections first."
    )


# ==============================================================================
# Phase 8 — Targeted Structured AI Extraction Endpoints
# ==============================================================================

@router.post("/{document_id}/extract", response_model=DocumentExtractionResult)
async def extract_document_fields_endpoint(document_id: str) -> DocumentExtractionResult:
    """
    Execute Phase 8 targeted structured AI extraction:
    1. Validate document exists.
    2. Check classification & sections preconditions.
    3. If document_type == 'unknown', returns skipped payload without invoking Gemini.
    4. Performs targeted section extraction using Gemini with section-specific schemas.
    5. Preserves field-level confidence, source text, and provenance.
    6. Persists fields in Supabase extracted_fields table and saves extraction.json artifact.
    7. Updates document status to 'extracted'.
    8. Records audit logs in processing_logs table.
    9. Returns DocumentExtractionResult.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured. Please set SUPABASE credentials."
        )

    # 1. Fetch document record
    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))

    # Precondition 1: OCR must be completed
    ocr_json_path = os.path.join(target_dir, "ocr.json")
    if not os.path.isfile(ocr_json_path) and doc.get("status") not in ("ocr_completed", "classified", "sectioned", "extracting", "extracted"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document must complete OCR before extraction."
        )

    # Precondition 2: Classification must be completed
    classification_json_path = os.path.join(target_dir, "classification.json")
    if not os.path.isfile(classification_json_path) and not doc.get("document_type"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document must be classified before extraction."
        )

    # Precondition 3: Sections must be detected
    sections_json_path = os.path.join(target_dir, "sections.json")
    section_result: Optional[DocumentSectionResult] = None
    if os.path.isfile(sections_json_path):
        try:
            with open(sections_json_path, "r", encoding="utf-8") as f:
                sec_data = json.load(f)
            section_result = DocumentSectionResult.model_validate(sec_data)
        except Exception as err:
            logger.warning(f"Could not parse local sections.json for {document_id}: {err}")

    if not section_result:
        # Fallback to database
        db_sections = supabase_service.get_document_sections(document_id)
        doc_type = doc.get("document_type") or "unknown"
        if db_sections or doc_type == "unknown" or doc.get("status") in ("sectioned", "extracting", "extracted"):
            sections_list = [
                DocumentSection(
                    section_id=s.get("id") or str(uuid.uuid4()),
                    document_id=document_id,
                    section_name=s.get("section_name", "unknown"),
                    page_number=s.get("page_number", 1),
                    text=s.get("raw_text", ""),
                    confidence=float(s.get("confidence", 0.0) or 0.0),
                    block_ids=[],
                    bbox=None,
                )
                for s in db_sections
            ]
            section_result = DocumentSectionResult(
                document_id=document_id,
                document_type=doc_type,
                sections=sections_list,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document must complete section detection before extraction."
            )

    # 3. Transition document status to 'extracting' & record audit log
    start_time = time.time()
    try:
        supabase_service.update_document_status(document_id, "extracting")
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="extraction",
            status="started",
            message="Structured extraction started",
            metadata={
                "document_type": section_result.document_type,
                "sections_count": len(section_result.sections),
            }
        )
    except Exception as log_err:
        logger.warning(f"Failed to record extraction started log for {document_id}: {log_err}")

    # 4. Run targeted extraction
    try:
        extraction_result = extract_document_fields(section_result)
    except GeminiNotConfiguredError as cfg_err:
        duration_ms = int((time.time() - start_time) * 1000)
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="extraction",
                status="failed",
                message=str(cfg_err),
                metadata={"processing_duration_ms": duration_ms}
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(cfg_err)
        )
    except GeminiServiceError as gem_err:
        duration_ms = int((time.time() - start_time) * 1000)
        err_msg = f"AI extraction failed: {str(gem_err)}"
        logger.error(f"Gemini extraction error for {document_id}: {err_msg}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="extraction",
                status="failed",
                message=err_msg,
                metadata={"processing_duration_ms": duration_ms}
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=err_msg
        )
    except Exception as general_err:
        duration_ms = int((time.time() - start_time) * 1000)
        err_msg = f"Extraction processing error: {str(general_err)}"
        logger.error(f"Unexpected error extracting fields for {document_id}: {err_msg}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="extraction",
                status="failed",
                message=err_msg,
                metadata={"processing_duration_ms": duration_ms}
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during structured extraction. Please check server logs."
        )

    duration_ms = int((time.time() - start_time) * 1000)

    # 5. Persist fields to Supabase extracted_fields table (if not skipped)
    if extraction_result.status != "skipped":
        try:
            supabase_service.insert_extracted_fields(document_id, extraction_result.fields)
        except Exception as db_fields_err:
            logger.warning(f"Failed to insert extracted fields to DB for {document_id}: {db_fields_err}")

        # 6. Update document status to 'extracted'
        try:
            supabase_service.update_document_status(document_id, "extracted")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="extraction",
                status="completed",
                message="Structured extraction completed successfully",
                metadata={
                    "sections_processed": extraction_result.metadata.get("sections_processed", len(section_result.sections)),
                    "fields_extracted": len(extraction_result.fields),
                    "document_type": extraction_result.document_type,
                    "processing_duration_ms": duration_ms,
                }
            )
        except Exception as db_err:
            logger.warning(f"Failed to update document status to extracted for {document_id}: {db_err}")
    else:
        # If skipped, record log
        try:
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="extraction",
                status="completed",
                message="Structured extraction skipped (unsupported document type)",
                metadata={
                    "sections_processed": 0,
                    "fields_extracted": 0,
                    "document_type": extraction_result.document_type,
                    "reason": extraction_result.reason,
                    "processing_duration_ms": duration_ms,
                }
            )
        except Exception:
            pass

    return extraction_result


@router.get("/{document_id}/extraction", response_model=DocumentExtractionResult)
async def get_document_extraction_endpoint(document_id: str) -> DocumentExtractionResult:
    """
    Retrieve stored structured extraction results for an existing document.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))
    extraction_json_path = os.path.join(target_dir, "extraction.json")

    if os.path.isfile(extraction_json_path):
        try:
            with open(extraction_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return DocumentExtractionResult.model_validate(data)
        except Exception as err:
            logger.error(f"Failed to read extraction.json for {document_id}: {err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to parse stored extraction: {str(err)}"
            )

    # Fallback to database query if artifact not on local disk
    db_fields = supabase_service.get_extracted_fields(document_id)
    if db_fields:
        fields_list = [
            ExtractedField(
                id=f.get("id") or str(uuid.uuid4()),
                field_name=f.get("field_name", "unknown"),
                field_value=f.get("field_value"),
                confidence=float(f.get("confidence", 0.0)) if f.get("confidence") is not None else None,
                source=f.get("source") or "gemini",
                source_text=f.get("source_text"),
                section_name="database",
                page_number=1,
            )
            for f in db_fields
        ]
        return DocumentExtractionResult(
            document_id=document_id,
            document_type=doc.get("document_type") or "unknown",
            status="extracted",
            fields=fields_list,
            section_data={},
            extracted_at=str(doc.get("updated_at") or datetime.utcnow().isoformat() + "Z"),
            metadata={"source": "database"},
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Extraction result not found for document '{document_id}'. Run POST /api/documents/{document_id}/extract first."
    )


# ==============================================================================
# PHASE 9: Normalization & Deterministic Validation Endpoints
# ==============================================================================

@router.post("/{document_id}/validate", response_model=DocumentValidationResult)
async def validate_document_endpoint(document_id: str) -> DocumentValidationResult:
    """
    Execute deterministic normalization and validation on extracted document fields.
    Zero AI/Gemini usage. Verifies dates, numbers, formats, line math, subtotal, and tax arithmetic.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    # 1. Verify document exists
    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    # 2. Verify extraction has completed (Preconditions)
    doc_status = doc.get("status")
    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))
    extraction_json_path = os.path.join(target_dir, "extraction.json")

    has_extraction_artifact = os.path.isfile(extraction_json_path)
    allowed_statuses = ("extracted", "validating", "completed", "needs_review")

    if not has_extraction_artifact and doc_status not in allowed_statuses:
        # Check specific preceding stages for precise error messages
        if doc_status in ("uploaded", "preprocessing", "preprocessed"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document must complete OCR before validation."
            )
        elif doc_status in ("ocr", "ocr_completed"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document must be classified before validation."
            )
        elif doc_status == "classified":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document must complete section detection before validation."
            )
        elif doc_status in ("sectioned", "extracting"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document must complete structured extraction before validation."
            )

    # 3. Load extracted fields and section data
    fields: List[ExtractedField] = []
    section_data: dict = {}
    doc_type = doc.get("document_type") or "unknown"

    if has_extraction_artifact:
        try:
            with open(extraction_json_path, "r", encoding="utf-8") as f:
                ext_data = json.load(f)
            doc_type = ext_data.get("document_type") or doc_type
            section_data = ext_data.get("section_data") or {}
            for item in ext_data.get("fields", []):
                fields.append(ExtractedField.model_validate(item))
        except Exception as err:
            logger.error(f"Failed to read extraction artifact for {document_id}: {err}")

    # Fallback to database if no artifact on disk
    if not fields:
        db_fields = supabase_service.get_extracted_fields(document_id)
        if db_fields:
            for f in db_fields:
                fields.append(
                    ExtractedField(
                        id=f.get("id") or str(uuid.uuid4()),
                        section_id=f.get("section_id"),
                        field_name=f.get("field_name", "unknown"),
                        field_value=f.get("field_value"),
                        confidence=float(f.get("confidence", 0.0)) if f.get("confidence") is not None else None,
                        source=f.get("source") or "gemini",
                        source_text=f.get("source_text"),
                        section_name="database",
                        page_number=1,
                    )
                )

    if not fields and doc_type != "unknown":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No extracted fields found for document. Please run extraction first."
        )

    # 4. Status transition to 'validating' & audit log for normalization
    start_time = time.time()
    try:
        supabase_service.update_document_status(document_id, "validating")
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="normalization",
            status="started",
            message="Field normalization started",
            metadata={"field_count": len(fields)}
        )
    except Exception as log_err:
        logger.warning(f"Failed to record validation started log for {document_id}: {log_err}")

    # 5. Run deterministic normalization & validation
    try:
        validator = DocumentValidator()
        validation_result = validator.normalize_and_validate(
            document_id=document_id,
            document_type=doc_type,
            fields=fields,
            section_data=section_data,
        )
    except Exception as val_err:
        duration_ms = int((time.time() - start_time) * 1000)
        err_msg = f"Deterministic validation encountered an internal error: {str(val_err)}"
        logger.error(f"Validation error for {document_id}: {err_msg}")
        try:
            supabase_service.update_document_status(document_id, "failed")
            supabase_service.create_processing_log(
                document_id=document_id,
                stage="validation",
                status="failed",
                message=err_msg,
                metadata={"processing_duration_ms": duration_ms}
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during deterministic validation."
        )

    duration_ms = int((time.time() - start_time) * 1000)

    # 6. Save local validation.json artifact
    try:
        os.makedirs(target_dir, exist_ok=True)
        validation_json_path = os.path.join(target_dir, "validation.json")
        with open(validation_json_path, "w", encoding="utf-8") as f:
            f.write(validation_result.model_dump_json(indent=2))
    except Exception as art_err:
        logger.warning(f"Could not persist validation.json for {document_id}: {art_err}")

    # 7. Persist validated fields to Supabase extracted_fields
    try:
        supabase_service.save_validated_fields(document_id, validation_result.fields)
    except Exception as db_fields_err:
        logger.warning(f"Could not update extracted_fields in DB for {document_id}: {db_fields_err}")

    # 8. Update document status to completed or needs_review
    final_status = validation_result.document_status
    try:
        supabase_service.update_document_status(document_id, final_status)
    except Exception as db_status_err:
        logger.warning(f"Could not update document status to {final_status} for {document_id}: {db_status_err}")

    # 9. Record completed audit logs for normalization and validation stages
    try:
        normalized_count = sum(1 for f in validation_result.fields if f.normalized_value is not None)
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="normalization",
            status="completed",
            message="Field normalization completed successfully",
            metadata={
                "field_count": len(validation_result.fields),
                "normalized_count": normalized_count,
            }
        )
        supabase_service.create_processing_log(
            document_id=document_id,
            stage="validation",
            status="completed",
            message=f"Deterministic validation completed with status: {final_status}",
            metadata={
                "total_fields": validation_result.summary.total_fields,
                "valid_count": validation_result.summary.valid_count,
                "needs_review_count": validation_result.summary.needs_review_count,
                "conflict_count": validation_result.summary.conflict_count,
                "document_status": final_status,
                "processing_duration_ms": duration_ms,
            }
        )
    except Exception as log_err:
        logger.warning(f"Failed to record completed validation logs for {document_id}: {log_err}")

    return validation_result


@router.get("/{document_id}/validation", response_model=DocumentValidationResult)
async def get_document_validation_endpoint(document_id: str) -> DocumentValidationResult:
    """
    Retrieve stored deterministic validation results for an existing document.
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    doc = supabase_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )

    target_dir = os.path.abspath(os.path.join(BASE_TMP_DIR, document_id))
    validation_json_path = os.path.join(target_dir, "validation.json")

    if os.path.isfile(validation_json_path):
        try:
            with open(validation_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return DocumentValidationResult.model_validate(data)
        except Exception as err:
            logger.error(f"Failed to read validation.json for {document_id}: {err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to parse stored validation: {str(err)}"
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Validation result not found for document '{document_id}'. Run POST /api/documents/{document_id}/validate first."
    )

