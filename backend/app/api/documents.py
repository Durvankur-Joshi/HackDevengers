import os
import re
import uuid
import logging
import glob
import json
from typing import Optional, List
from PIL import Image
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from app.schemas import DocumentResponse, DocumentPreviewResponse
from app.pipeline.types import (
    PreprocessingResult,
    OCRDocumentResult,
    PreprocessedPage,
    DocumentClassificationResult,
)
from app.pipeline.ocr import get_ocr_engine, OCREngineUnavailableError, OCREngineError
from app.pipeline.classifier import classify_document
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
