import os
import re
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from app.schemas import DocumentResponse, DocumentPreviewResponse
from app.services.supabase import supabase_service
from app.services.storage import storage_service

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
