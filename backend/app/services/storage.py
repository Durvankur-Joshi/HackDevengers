import logging
from typing import Optional
from app.services.supabase import supabase_service

logger = logging.getLogger(__name__)

DEFAULT_BUCKET = "documents"


class StorageService:
    """
    Storage service abstraction encapsulating all Supabase Storage interactions.
    Provides safe file upload, signed URL generation, and cleanup.
    """

    def __init__(self, default_bucket: str = DEFAULT_BUCKET):
        self.default_bucket = default_bucket

    def upload_file(
        self,
        file_bytes: bytes,
        storage_path: str,
        mime_type: str = "application/octet-stream",
        bucket_name: Optional[str] = None
    ) -> str:
        """
        Upload binary document data to Supabase Storage.
        Returns the confirmed storage path.
        """
        client = supabase_service.get_client()
        if not client:
            raise RuntimeError("Supabase client is not configured or unavailable.")

        target_bucket = bucket_name or self.default_bucket

        try:
            # Upload with upsert enabled to prevent fatal collisions on re-upload
            res = client.storage.from_(target_bucket).upload(
                path=storage_path,
                file=file_bytes,
                file_options={"content-type": mime_type, "upsert": "true"}
            )
            logger.info(f"File successfully uploaded to Supabase Storage: {storage_path}")
            return storage_path
        except Exception as e:
            logger.error(f"Failed to upload file to Supabase Storage path '{storage_path}': {e}")
            raise RuntimeError(f"Storage upload error: {str(e)}")

    def create_signed_url(
        self,
        storage_path: str,
        expires_in: int = 3600,
        bucket_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a temporary, secure signed URL for previewing or downloading a document.
        Does not expose service keys to the frontend.
        """
        client = supabase_service.get_client()
        if not client or not storage_path:
            return None

        target_bucket = bucket_name or self.default_bucket

        try:
            res = client.storage.from_(target_bucket).create_signed_url(
                path=storage_path,
                expires_in=expires_in
            )
            if isinstance(res, dict):
                return res.get("signedURL") or res.get("signedUrl")
            elif hasattr(res, "signed_url"):
                return res.signed_url
            elif hasattr(res, "signedURL"):
                return res.signedURL
            return str(res) if res else None
        except Exception as e:
            logger.warning(f"Could not generate signed URL for '{storage_path}': {e}")
            # Fallback to public URL attempt
            try:
                pub = client.storage.from_(target_bucket).get_public_url(storage_path)
                return pub
            except Exception:
                return None

    def delete_file(
        self,
        storage_path: str,
        bucket_name: Optional[str] = None
    ) -> bool:
        """Delete an uploaded document from Supabase Storage."""
        client = supabase_service.get_client()
        if not client or not storage_path:
            return False

        target_bucket = bucket_name or self.default_bucket

        try:
            client.storage.from_(target_bucket).remove([storage_path])
            return True
        except Exception as e:
            logger.warning(f"Failed to remove file from Supabase Storage '{storage_path}': {e}")
            return False


storage_service = StorageService()
