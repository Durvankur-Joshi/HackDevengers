import sys
import os
import io
import json
import shutil
import time
from typing import List
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import fitz  # PyMuPDF
from fastapi.testclient import TestClient

# Ensure backend root is first in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, "../.."))
if current_dir in sys.path:
    sys.path.remove(current_dir)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.main import app
from app.pipeline.types import (
    PreprocessedPage,
    PreprocessingResult,
    BoundingBox,
    OCRBlock,
    OCRPageResult,
    OCRMetadata,
    OCRDocumentResult,
)
from app.pipeline.preprocessing import (
    preprocess_pdf,
    preprocess_image,
    BASE_TMP_DIR,
    _ensure_clean_dir,
)
from app.pipeline.ocr import (
    get_ocr_engine,
    TesseractOCREngine,
    BaseOCREngine,
    OCREngineError,
    OCREngineUnavailableError,
)

client = TestClient(app)


def create_invoice_pdf() -> bytes:
    """Create a realistic invoice PDF."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = (
        "INVOICE #INV-2026-0042\n"
        "Date: 2026-09-15\n"
        "Due Date: 2026-10-15\n\n"
        "Vendor: TechCorp Global Solutions\n"
        "Customer: Acme Enterprises Inc\n\n"
        "Description              Qty    Unit Price    Total\n"
        "Cloud Infrastructure       1      $1200.00   $1200.00\n"
        "Consulting Services       10       $150.00   $1500.00\n\n"
        "Subtotal: $2700.00\n"
        "Tax (10%): $270.00\n"
        "Grand Total: $2970.00\n"
    )
    page.insert_text((50, 70), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_resume_pdf() -> bytes:
    """Create a sample resume PDF with standard sections."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    resume_text = (
        "ALEXANDER MORGAN\n"
        "Email: alex.morgan@example.com | Phone: +1-555-0199\n\n"
        "EDUCATION\n"
        "Bachelor of Science in Computer Science\n"
        "Stanford University, 2020 - 2024\n\n"
        "SKILLS\n"
        "Languages: Python, JavaScript, TypeScript, SQL, Go\n"
        "Frameworks: FastAPI, React, Node.js, Next.js\n"
        "Cloud & Tools: Supabase, Docker, Git, PostgreSQL\n\n"
        "EXPERIENCE\n"
        "Software Engineering Intern - Cloud Systems\n"
        "Developed high-throughput document processing pipelines\n"
        "Optimized OCR extraction and database storage layers\n\n"
        "PROJECTS\n"
        "Document-to-Action Intelligent Automation Pipeline\n"
        "Automated multimodal data extraction from messy invoices and forms\n"
    )
    page.insert_text((50, 70), resume_text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_multipage_pdf(num_pages: int = 3) -> bytes:
    """Create a multi-page PDF document."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            (50, 70),
            f"MULTI-PAGE DOCUMENT - SECTION {i + 1}\n"
            f"This is official page number {i + 1} of the multi-page document.\n"
            f"Processing token: SEC-{i + 1}-VALIDATION-PASS\n",
            fontsize=14
        )
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_noisy_image() -> bytes:
    """Create an image with low contrast / noisy text to test robustness."""
    img = Image.new("RGB", (600, 200), color=(210, 210, 210))
    d = ImageDraw.Draw(img)
    d.text((20, 40), "NOISY SCAN SAMPLE TEXT 123", fill=(170, 170, 170))
    # Apply blur
    img = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_1_engine_detection():
    print("\n--- 1. Testing OCR Engine Detection & Configuration ---")
    engine = get_ocr_engine()
    available, msg = engine.is_available()
    print(f"  [INFO] Engine name: {engine.engine_name}")
    print(f"  [INFO] Availability: {available} ({msg})")
    assert available, f"Expected OCR engine to be available: {msg}"
    print("  [OK] OCR Engine successfully detected and verified.")


def test_2_single_page_invoice_ocr():
    print("\n--- 2. Testing Single-Page Invoice OCR ---")
    doc_id = "test_doc_invoice"
    target_dir = os.path.join(BASE_TMP_DIR, doc_id)
    _ensure_clean_dir(target_dir)

    pdf_bytes = create_invoice_pdf()
    pages = preprocess_pdf(pdf_bytes, target_dir)
    assert len(pages) == 1

    engine = get_ocr_engine()
    ocr_res = engine.extract_document(doc_id, pages)

    assert ocr_res.document_id == doc_id
    assert ocr_res.page_count == 1
    assert len(ocr_res.pages) == 1
    assert len(ocr_res.pages[0].blocks) > 0
    assert ocr_res.metadata.block_count > 0
    assert ocr_res.metadata.average_confidence is not None
    assert ocr_res.metadata.average_confidence > 50.0

    # Verify recognized keywords
    full_lower = ocr_res.full_text.lower()
    assert "invoice" in full_lower
    assert "techcorp" in full_lower or "acme" in full_lower
    assert "2970" in full_lower or "total" in full_lower

    # Verify bounding boxes
    for block in ocr_res.pages[0].blocks:
        assert block.bbox.x >= 0
        assert block.bbox.y >= 0
        assert block.bbox.width > 0
        assert block.bbox.height > 0
        assert block.page_number == 1
        assert block.block_index >= 0

    print(f"  [OK] Invoice OCR: {ocr_res.metadata.block_count} blocks, avg confidence: {ocr_res.metadata.average_confidence}%")
    shutil.rmtree(target_dir, ignore_errors=True)


def test_3_multipage_pdf_ocr():
    print("\n--- 3. Testing Multi-Page PDF OCR (3 Pages) ---")
    doc_id = "test_doc_multipage"
    target_dir = os.path.join(BASE_TMP_DIR, doc_id)
    _ensure_clean_dir(target_dir)

    pdf_bytes = create_multipage_pdf(3)
    pages = preprocess_pdf(pdf_bytes, target_dir)
    assert len(pages) == 3

    engine = get_ocr_engine()
    ocr_res = engine.extract_document(doc_id, pages)

    assert ocr_res.page_count == 3
    assert len(ocr_res.pages) == 3

    # Check page-separated full_text
    assert "--- PAGE 1 ---" in ocr_res.full_text
    assert "--- PAGE 2 ---" in ocr_res.full_text
    assert "--- PAGE 3 ---" in ocr_res.full_text

    # Each page must have ordered blocks and proper page numbers
    for idx, pr in enumerate(ocr_res.pages):
        expected_page = idx + 1
        assert pr.page_number == expected_page
        assert len(pr.blocks) > 0
        for b in pr.blocks:
            assert b.page_number == expected_page
        print(f"  [OK] Page {pr.page_number}: {len(pr.blocks)} blocks extracted.")

    print(f"  [OK] Multi-page OCR completed successfully. Total blocks: {ocr_res.metadata.block_count}")
    shutil.rmtree(target_dir, ignore_errors=True)


def test_4_resume_quality_test():
    print("\n--- 4. Testing Resume PDF OCR Quality ---")
    doc_id = "test_doc_resume"
    target_dir = os.path.join(BASE_TMP_DIR, doc_id)
    _ensure_clean_dir(target_dir)

    pdf_bytes = create_resume_pdf()
    pages = preprocess_pdf(pdf_bytes, target_dir)

    engine = get_ocr_engine()
    ocr_res = engine.extract_document(doc_id, pages)

    text_lower = ocr_res.full_text.lower()
    # Verify core resume sections and information
    expected_terms = ["morgan", "education", "skills", "experience", "projects"]
    found_terms = [t for t in expected_terms if t in text_lower]

    print(f"  [INFO] Found resume keywords: {found_terms} / {expected_terms}")
    assert len(found_terms) >= 4, f"Expected at least 4 resume keywords, found: {found_terms}"
    print("  [OK] Resume OCR successfully extracted recognizable professional sections.")
    shutil.rmtree(target_dir, ignore_errors=True)


def test_5_image_formats_png_and_jpg():
    print("\n--- 5. Testing Image Formats (PNG & JPG) ---")
    engine = get_ocr_engine()

    # 1. PNG
    png_id = "test_doc_png"
    png_dir = os.path.join(BASE_TMP_DIR, png_id)
    _ensure_clean_dir(png_dir)

    png_img = Image.new("RGBA", (500, 150), (255, 255, 255, 255))
    d = ImageDraw.Draw(png_img)
    d.text((30, 40), "PNG FORMAT TEST PASSED", fill=(0, 0, 0))
    png_bytes = io.BytesIO()
    png_img.save(png_bytes, format="PNG")

    png_pages = preprocess_image(png_bytes.getvalue(), png_dir)
    png_ocr = engine.extract_document(png_id, png_pages)
    assert "png format" in png_ocr.full_text.lower()
    print(f"  [OK] PNG Image OCR passed: '{png_ocr.pages[0].blocks[0].text}'")
    shutil.rmtree(png_dir, ignore_errors=True)

    # 2. JPG
    jpg_id = "test_doc_jpg"
    jpg_dir = os.path.join(BASE_TMP_DIR, jpg_id)
    _ensure_clean_dir(jpg_dir)

    jpg_img = Image.new("RGB", (500, 150), (250, 250, 250))
    d = ImageDraw.Draw(jpg_img)
    d.text((30, 40), "JPG FORMAT TEST PASSED", fill=(20, 20, 20))
    jpg_bytes = io.BytesIO()
    jpg_img.save(jpg_bytes, format="JPEG")

    jpg_pages = preprocess_image(jpg_bytes.getvalue(), jpg_dir)
    jpg_ocr = engine.extract_document(jpg_id, jpg_pages)
    assert "jpg format" in jpg_ocr.full_text.lower()
    print(f"  [OK] JPG Image OCR passed: '{jpg_ocr.pages[0].blocks[0].text}'")
    shutil.rmtree(jpg_dir, ignore_errors=True)


def test_6_noisy_document_robustness():
    print("\n--- 6. Testing Noisy / Low-Quality Document Robustness ---")
    doc_id = "test_doc_noisy"
    target_dir = os.path.join(BASE_TMP_DIR, doc_id)
    _ensure_clean_dir(target_dir)

    noisy_bytes = create_noisy_image()
    pages = preprocess_image(noisy_bytes, target_dir)

    engine = get_ocr_engine()
    # Must not throw unhandled exception or crash
    ocr_res = engine.extract_document(doc_id, pages)
    assert ocr_res.page_count == 1
    print(f"  [OK] Noisy image processed without crashing. Blocks detected: {ocr_res.metadata.block_count}")
    shutil.rmtree(target_dir, ignore_errors=True)


def test_7_reading_order_determinism():
    print("\n--- 7. Testing Deterministic Reading Order ---")
    doc_id = "test_doc_reading_order"
    target_dir = os.path.join(BASE_TMP_DIR, doc_id)
    _ensure_clean_dir(target_dir)

    # Draw three lines at distinct Y coordinates
    img = Image.new("RGB", (600, 400), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50, 50), "FIRST LINE AT TOP", fill=(0, 0, 0))
    d.text((50, 150), "SECOND LINE IN MIDDLE", fill=(0, 0, 0))
    d.text((50, 250), "THIRD LINE AT BOTTOM", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    pages = preprocess_image(buf.getvalue(), target_dir)
    engine = get_ocr_engine()
    ocr_res = engine.extract_document(doc_id, pages)

    blocks = ocr_res.pages[0].blocks
    assert len(blocks) >= 3

    # Check y coordinates are monotonically non-decreasing
    y_coords = [b.bbox.y for b in blocks]
    assert y_coords == sorted(y_coords), f"Blocks not sorted by vertical position: {y_coords}"
    assert blocks[0].block_index == 0
    assert blocks[1].block_index == 1
    assert blocks[2].block_index == 2
    print(f"  [OK] Blocks sorted deterministically by reading order (Y coords: {y_coords[:3]})")
    shutil.rmtree(target_dir, ignore_errors=True)


def test_8_api_endpoints():
    print("\n--- 8. Testing OCR API Endpoints ---")
    # 1. Test 404 on nonexistent document
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.post(f"/api/documents/{fake_id}/ocr")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print(f"  [OK] POST /api/documents/{fake_id}/ocr returned 404 as expected: {resp.json().get('detail')}")

    # 2. Test GET on nonexistent document
    resp_get = client.get(f"/api/documents/{fake_id}/ocr")
    assert resp_get.status_code == 404
    print(f"  [OK] GET /api/documents/{fake_id}/ocr returned 404 as expected: {resp_get.json().get('detail')}")


if __name__ == "__main__":
    print("==================================================")
    print("PHASE 5: OCR EXTRACTION & LAYOUT TEST SUITE")
    print("==================================================")
    test_1_engine_detection()
    test_2_single_page_invoice_ocr()
    test_3_multipage_pdf_ocr()
    test_4_resume_quality_test()
    test_5_image_formats_png_and_jpg()
    test_6_noisy_document_robustness()
    test_7_reading_order_determinism()
    test_8_api_endpoints()
    print("\n==================================================")
    print("ALL PHASE 5 OCR TESTS COMPLETED SUCCESSFULLY!")
    print("==================================================")
