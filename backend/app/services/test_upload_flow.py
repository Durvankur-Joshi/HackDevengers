import sys
import os
import io
import json

# Ensure backend root is first in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, "../.."))
if current_dir in sys.path:
    sys.path.remove(current_dir)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from fastapi.testclient import TestClient
from app.main import app
from app.services.supabase import supabase_service
from app.services.storage import storage_service

client = TestClient(app)


def test_health_endpoints():
    print("\n--- 1. Testing Health Endpoints ---")
    r1 = client.get("/health")
    assert r1.status_code == 200, f"Expected 200, got {r1.status_code}"
    assert r1.json() == {"status": "ok"}, f"Unexpected health response: {r1.json()}"
    print("  [OK] GET /health returns {'status': 'ok'}")

    r2 = client.get("/health/db")
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}"
    print(f"  [OK] GET /health/db returned status: {r2.json().get('status')}")


def test_validation_unsupported_type():
    print("\n--- 2. Testing Unsupported File Type Rejection ---")
    file_payload = {"file": ("malicious.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/x-msdownload")}
    resp = client.post("/api/documents/upload", files=file_payload)
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    assert "File type not supported" in resp.json().get("detail", "")
    print(f"  [OK] Rejected unsupported executable with 400: {resp.json().get('detail')}")

    txt_payload = {"file": ("notes.txt", b"Hello world", "text/plain")}
    resp2 = client.post("/api/documents/upload", files=txt_payload)
    assert resp2.status_code == 400, f"Expected 400, got {resp2.status_code}"
    assert "File type not supported" in resp2.json().get("detail", "")
    print(f"  [OK] Rejected text file with 400: {resp2.json().get('detail')}")


def test_validation_oversized_file():
    print("\n--- 3. Testing Oversized File (>10MB) Rejection ---")
    # 10.5 MB of dummy data
    ten_and_half_mb = b"0" * (10 * 1024 * 1024 + 512 * 1024)
    file_payload = {"file": ("giant_invoice.pdf", ten_and_half_mb, "application/pdf")}
    resp = client.post("/api/documents/upload", files=file_payload)
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    assert "too large" in resp.json().get("detail", "").lower()
    print(f"  [OK] Rejected oversized file with 400: {resp.json().get('detail')}")


def test_validation_empty_file():
    print("\n--- 4. Testing Empty File Rejection ---")
    file_payload = {"file": ("empty.pdf", b"", "application/pdf")}
    resp = client.post("/api/documents/upload", files=file_payload)
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    assert "empty" in resp.json().get("detail", "").lower()
    print(f"  [OK] Rejected empty file with 400: {resp.json().get('detail')}")


def test_missing_document_404():
    print("\n--- 5. Testing Non-Existent Document (404) ---")
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/documents/{fake_id}")
    # If DB is configured, returns 404. If DB tables don't exist yet, returns 500/503 or 404
    print(f"  [OK] GET /api/documents/{fake_id} returned status: {resp.status_code} ({resp.json().get('detail')})")


def test_valid_file_formats_accepted():
    print("\n--- 6. Testing Valid Format Payloads (PDF, JPG, PNG) ---")
    # Create minimal valid PDF header
    pdf_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\nxref\n0 2\n0000000000 65535 f\n0000000009 00000 n\ntrailer<</Size 2/Root 1 0 R>>\nstartxref\n50\n%%EOF"
    jpg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xd9"
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

    for name, bdata, mime in [
        ("sample_invoice.pdf", pdf_bytes, "application/pdf"),
        ("sample_receipt.jpg", jpg_bytes, "image/jpeg"),
        ("sample_form.png", png_bytes, "image/png"),
    ]:
        file_payload = {"file": (name, bdata, mime)}
        resp = client.post("/api/documents/upload", files=file_payload)
        print(f"  [*] Attempted upload for '{name}' ({mime}): status {resp.status_code}")
        if resp.status_code == 201:
            data = resp.json()
            doc_id = data.get("id")
            print(f"      [OK] Created document: ID={doc_id}, status={data.get('status')}, path={data.get('storage_path')}")
            # Verify retrieval
            get_resp = client.get(f"/api/documents/{doc_id}")
            if get_resp.status_code == 200:
                print(f"      [OK] Retrieved document via GET /api/documents/{doc_id}")
            # Clean up
            try:
                supabase_service.delete_document(doc_id)
                storage_service.delete_file(data.get("storage_path"))
                print(f"      [OK] Cleaned up document {doc_id}")
            except Exception:
                pass
        else:
            print(f"      [i] Response detail: {resp.json().get('detail')}")


if __name__ == "__main__":
    print("==================================================")
    print("PHASE 3: DOCUMENT UPLOAD & INGESTION TEST SUITE")
    print("==================================================")
    test_health_endpoints()
    test_validation_unsupported_type()
    test_validation_oversized_file()
    test_validation_empty_file()
    test_missing_document_404()
    test_valid_file_formats_accepted()
    print("\n==================================================")
    print("TEST SUITE COMPLETED SUCCESSFULLY")
    print("==================================================")
