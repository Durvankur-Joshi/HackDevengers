import logging
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)


class SupabaseService:
    """
    Supabase client and database abstraction service.
    Encapsulates all Supabase PostgreSQL interactions for the Document-to-Action pipeline.
    """

    def __init__(self):
        self._client = None
        self._init_attempted = False

    def is_configured(self) -> bool:
        """Verify whether valid Supabase configuration variables are set."""
        url = (settings.SUPABASE_URL or "").strip()
        key = (settings.SUPABASE_KEY or "").strip()
        return bool(url and key and url.startswith("http"))

    def get_client(self):
        """Lazily initialize and return the Supabase client."""
        if not self.is_configured():
            return None

        if self._client is None:
            try:
                from supabase._sync.client import create_client, Client
                self._client = create_client(settings.SUPABASE_URL.strip(), settings.SUPABASE_KEY.strip())
                logger.info("Supabase client successfully initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                self._client = None

        return self._client

    def check_connection(self) -> Dict[str, Any]:
        """
        Verify connectivity to Supabase PostgreSQL database.
        Returns a clean status payload without leaking credentials.
        """
        if not self.is_configured():
            return {
                "status": "unconfigured",
                "database": "disconnected",
                "message": "SUPABASE_URL or SUPABASE_KEY not configured in backend/.env"
            }

        client = self.get_client()
        if client is None:
            return {
                "status": "error",
                "database": "disconnected",
                "message": "Failed to create Supabase client with provided credentials"
            }

        try:
            # Query the documents table with limit 1
            response = client.table("documents").select("id").limit(1).execute()
            return {
                "status": "ok",
                "database": "connected"
            }
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"Supabase connection test failed: {err_msg}")
            return {
                "status": "error",
                "database": "disconnected",
                "message": f"Database query failed: {err_msg}"
            }

    def insert_document(
        self,
        filename: str,
        document_id: Optional[str] = None,
        document_type: Optional[str] = "unknown",
        status: str = "uploaded",
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        storage_path: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a new document metadata record into the documents table."""
        client = self.get_client()
        if not client:
            raise RuntimeError("Supabase client is not configured.")

        payload = {
            "filename": filename,
            "document_type": document_type,
            "status": status,
        }
        if document_id:
            payload["id"] = document_id
        if mime_type:
            payload["mime_type"] = mime_type
        if file_size is not None:
            payload["file_size"] = file_size
        if storage_path:
            payload["storage_path"] = storage_path
        if summary:
            payload["summary"] = summary

        res = client.table("documents").insert(payload).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        raise RuntimeError("No data returned from document insert operation.")

    def update_document_status(
        self,
        document_id: str,
        status: str,
        storage_path: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Update the status and optional storage_path of an existing document."""
        client = self.get_client()
        if not client:
            raise RuntimeError("Supabase client is not configured.")

        payload = {"status": status}
        if storage_path:
            payload["storage_path"] = storage_path

        res = client.table("documents").update(payload).eq("id", document_id).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None

    def create_processing_log(
        self,
        document_id: str,
        stage: str,
        status: str,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Record an entry in the processing_logs table for pipeline auditability."""
        client = self.get_client()
        if not client:
            raise RuntimeError("Supabase client is not configured.")

        payload = {
            "document_id": document_id,
            "stage": stage,
            "status": status,
        }
        if message:
            payload["message"] = message
        if metadata:
            payload["metadata"] = metadata

        res = client.table("processing_logs").insert(payload).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return payload

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a document record by its UUID."""
        client = self.get_client()
        if not client:
            raise RuntimeError("Supabase client is not configured.")

        try:
            res = client.table("documents").select("*").eq("id", document_id).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
            return None
        except Exception as e:
            logger.warning(f"Error fetching document {document_id}: {e}")
            return None

    def delete_document(self, document_id: str) -> bool:
        """Delete a document record by its UUID (cascades to related tables)."""
        client = self.get_client()
        if not client:
            raise RuntimeError("Supabase client is not configured.")

        try:
            res = client.table("documents").delete().eq("id", document_id).execute()
            return bool(res.data and len(res.data) > 0)
        except Exception as e:
            logger.warning(f"Error deleting document {document_id}: {e}")
            return False

    def verify_roundtrip(self) -> Dict[str, Any]:
        """
        Lifecycle verification:
        1. Insert temporary test document 'phase2-test.pdf'.
        2. Retrieve and assert fields.
        3. Delete and clean up test record.
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "Supabase credentials not configured in backend/.env"
            }

        test_filename = "phase2-test.pdf"
        test_type = "unknown"
        test_status = "uploaded"

        # 1. Insert
        inserted = self.insert_document(
            filename=test_filename,
            document_type=test_type,
            status=test_status
        )
        doc_id = inserted.get("id")
        if not doc_id:
            return {
                "success": False,
                "error": "Insert succeeded but did not return a valid document ID"
            }

        # 2. Retrieve
        retrieved = self.get_document(doc_id)
        if not retrieved or retrieved.get("filename") != test_filename:
            # Clean up before erroring
            self.delete_document(doc_id)
            return {
                "success": False,
                "error": f"Failed to retrieve matching test document {doc_id}"
            }

        # 3. Clean up / Delete
        deleted = self.delete_document(doc_id)
        if not deleted:
            return {
                "success": False,
                "error": f"Failed to clean up test document {doc_id}",
                "inserted_id": doc_id
            }

        return {
            "success": True,
            "inserted_id": doc_id,
            "filename": test_filename,
            "document_type": test_type,
            "status": test_status,
            "cleaned_up": True
        }


# Global singleton instance
supabase_service = SupabaseService()
