import sys
import os
import io
import json
import shutil
from PIL import Image

# Ensure backend root is first in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, "../.."))
if current_dir in sys.path:
    sys.path.remove(current_dir)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

import fitz  # PyMuPDF
from fastapi.testclient import TestClient
from app.main import app
from app.pipeline.preprocessing import (
    preprocess_pdf,
    preprocess_image,
    _normalize_image,
    BASE_TMP_DIR
)
from app.pipeline.types import PreprocessedPage, PreprocessingResult

client = TestClient(app)


def create_sample_pdf(num_pages=3) -> bytes:
    """Generate an in-memory multi-page PDF document for testing."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)  # A4 dimensions
        # Insert sample text
        page.insert_text(
            (50, 72),
            f"Document-to-Action Invoice Sample - Page {i + 1}\nVendor: ACME Corporation\nTotal: $1,250.00",
            fontsize=16
        )
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_sample_image(format="PNG", mode="RGBA", size=(800, 1000)) -> bytes:
    """Generate an in-memory test image with sample geometry."""
    img = Image.new(mode, size, (240, 240, 240, 255) if mode == "RGBA" else (240, 240, 240))
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


def test_multipage_pdf_preprocessing():
    print("\n--- 1. Testing Multi-Page PDF Preprocessing (3 Pages) ---")
    pdf_bytes = create_sample_pdf(num_pages=3)
    test_out_dir = os.path.join(BASE_TMP_DIR, "test_doc_multi_pdf")
    os.makedirs(test_out_dir, exist_ok=True)

    pages = preprocess_pdf(pdf_bytes, test_out_dir)

    assert len(pages) == 3, f"Expected 3 pages, got {len(pages)}"
    for idx, p in enumerate(pages):
        expected_num = idx + 1
        assert p.page_number == expected_num, f"Page number mismatch: {p.page_number} != {expected_num}"
        assert os.path.exists(p.image_path), f"Output file does not exist: {p.image_path}"
        assert p.width > 0 and p.height > 0, f"Invalid dimensions: {p.width}x{p.height}"
        assert p.format == "png", f"Unexpected format: {p.format}"
        print(f"  [OK] Page {p.page_number}: {p.width}x{p.height} px, {p.file_size_bytes} bytes -> {os.path.basename(p.image_path)}")

    # Clean up test dir
    shutil.rmtree(test_out_dir, ignore_errors=True)
    print("  [OK] Multi-page PDF successfully rendered to ordered OCR-ready PNGs.")


def test_single_page_pdf_preprocessing():
    print("\n--- 2. Testing Single-Page PDF Preprocessing ---")
    pdf_bytes = create_sample_pdf(num_pages=1)
    test_out_dir = os.path.join(BASE_TMP_DIR, "test_doc_single_pdf")
    os.makedirs(test_out_dir, exist_ok=True)

    pages = preprocess_pdf(pdf_bytes, test_out_dir)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert os.path.exists(pages[0].image_path)
    shutil.rmtree(test_out_dir, ignore_errors=True)
    print("  [OK] Single-page PDF rendered and verified.")


def test_image_preprocessing_png():
    print("\n--- 3. Testing PNG Preprocessing (RGBA Alpha Handling) ---")
    png_bytes = create_sample_image(format="PNG", mode="RGBA", size=(600, 800))
    test_out_dir = os.path.join(BASE_TMP_DIR, "test_doc_png")
    os.makedirs(test_out_dir, exist_ok=True)

    pages = preprocess_image(png_bytes, test_out_dir)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert os.path.exists(pages[0].image_path)
    # Check rendered image is valid RGB
    with Image.open(pages[0].image_path) as img:
        assert img.mode == "RGB", f"Expected RGB mode, got {img.mode}"
    shutil.rmtree(test_out_dir, ignore_errors=True)
    print("  [OK] PNG successfully normalized to RGB OCR-ready page.")


def test_image_preprocessing_jpg():
    print("\n--- 4. Testing JPG Preprocessing ---")
    jpg_bytes = create_sample_image(format="JPEG", mode="RGB", size=(700, 900))
    test_out_dir = os.path.join(BASE_TMP_DIR, "test_doc_jpg")
    os.makedirs(test_out_dir, exist_ok=True)

    pages = preprocess_image(jpg_bytes, test_out_dir)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert os.path.exists(pages[0].image_path)
    shutil.rmtree(test_out_dir, ignore_errors=True)
    print("  [OK] JPG successfully preprocessed to OCR-ready PNG.")


def test_oversized_image_resizing():
    print("\n--- 5. Testing Oversized Image Scaling (Max 2400px) ---")
    huge_img = Image.new("RGB", (3500, 4200), (255, 255, 255))
    normalized = _normalize_image(huge_img)
    assert normalized.width <= 2400 and normalized.height <= 2400
    print(f"  [OK] Oversized image (3500x4200) scaled down to ({normalized.width}x{normalized.height}).")


def test_idempotency_cleans_previous_output():
    print("\n--- 6. Testing Idempotency (Cleaning Previous Output) ---")
    test_doc_id = "test-idempotent-doc"
    doc_dir = os.path.join(BASE_TMP_DIR, test_doc_id)
    os.makedirs(doc_dir, exist_ok=True)

    # Place a stale artifact
    stale_file = os.path.join(doc_dir, "stale_page_999.png")
    with open(stale_file, "w") as f:
        f.write("stale")

    assert os.path.exists(stale_file)

    # Run preprocessing on 1-page PDF
    pdf_bytes = create_sample_pdf(num_pages=1)
    from app.pipeline.preprocessing import _ensure_clean_dir
    _ensure_clean_dir(doc_dir)
    pages = preprocess_pdf(pdf_bytes, doc_dir)

    assert not os.path.exists(stale_file), "Stale file was not cleaned up!"
    assert len(pages) == 1
    assert os.path.exists(pages[0].image_path)

    shutil.rmtree(doc_dir, ignore_errors=True)
    print("  [OK] Preprocessing directory is cleaned idempotently on rerun.")


def test_corrupted_file_handling():
    print("\n--- 7. Testing Corrupted File Handling ---")
    garbage_bytes = b"NOT_A_REAL_DOCUMENT_CONTENT_RANDOM_BYTES"
    test_out_dir = os.path.join(BASE_TMP_DIR, "test_doc_corrupt")
    os.makedirs(test_out_dir, exist_ok=True)

    # PDF handler should reject
    try:
        preprocess_pdf(garbage_bytes, test_out_dir)
        assert False, "Should have raised ValueError on corrupt PDF"
    except ValueError as e:
        print(f"  [OK] Corrupt PDF cleanly rejected: {e}")

    # Image handler should reject
    try:
        preprocess_image(garbage_bytes, test_out_dir)
        assert False, "Should have raised ValueError on corrupt Image"
    except ValueError as e:
        print(f"  [OK] Corrupt Image cleanly rejected: {e}")

    shutil.rmtree(test_out_dir, ignore_errors=True)


def test_api_preprocess_endpoint_validation():
    print("\n--- 8. Testing Preprocess API Endpoint Validation ---")
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.post(f"/api/documents/{fake_id}/preprocess")
    # Missing document ID returns 404
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print(f"  [OK] POST /api/documents/{fake_id}/preprocess returned 404 as expected: {resp.json().get('detail')}")


if __name__ == "__main__":
    print("==================================================")
    print("PHASE 4: DOCUMENT PREPROCESSING TEST SUITE")
    print("==================================================")
    test_multipage_pdf_preprocessing()
    test_single_page_pdf_preprocessing()
    test_image_preprocessing_png()
    test_image_preprocessing_jpg()
    test_oversized_image_resizing()
    test_idempotency_cleans_previous_output()
    test_corrupted_file_handling()
    test_api_preprocess_endpoint_validation()
    print("\n==================================================")
    print("ALL PHASE 4 PREPROCESSING TESTS PASSED")
    print("==================================================")
