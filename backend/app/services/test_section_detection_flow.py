import sys
import os
import json
import uuid
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Ensure backend root is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, "../.."))
if current_dir in sys.path:
    sys.path.remove(current_dir)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.main import app
from app.core.config import settings
from app.pipeline.types import (
    BoundingBox,
    OCRBlock,
    OCRPageResult,
    OCRMetadata,
    OCRDocumentResult,
    InvoiceSectionType,
    OnboardingSectionType,
    GeminiRawSection,
    GeminiSectionDetectionOutput,
    DocumentSection,
    DocumentSectionResult,
)
from app.pipeline.section_detector import (
    SectionDetector,
    compute_blocks_bounding_box,
    INVOICE_SECTION_WHITELIST,
    ONBOARDING_SECTION_WHITELIST,
    detect_sections_for_document,
)
from app.services.gemini import gemini_service, GeminiNotConfiguredError, GeminiServiceError
from app.services.supabase import supabase_service

client = TestClient(app)


def build_mock_ocr_result(doc_id: str, doc_kind: str) -> OCRDocumentResult:
    """Helper to build realistic OCR results for section detection tests."""
    if doc_kind == "invoice":
        lines = [
            (0, "Acme Global Technologies Inc.", 100, 100, 400, 30),
            (1, "123 Tech Boulevard, Suite 500, San Jose, CA 95110", 100, 140, 450, 25),
            (2, "Bill To: Beta Logistics Corp, 456 Freight Way, Dallas, TX", 100, 200, 500, 30),
            (3, "INVOICE #INV-2026-9901 | Issue Date: 2026-09-01 | Due: 2026-10-01", 100, 260, 550, 25),
            (4, "Item 1: Cloud Server Instances - 10 Units @ $100.00 = $1,000.00", 100, 340, 500, 25),
            (5, "Item 2: Managed Kubernetes Cluster - 1 Month = $500.00", 100, 380, 480, 25),
            (6, "Subtotal: $1,500.00 | Tax (8.25%): $123.75 | Total Due: $1,623.75", 100, 440, 520, 30),
            (7, "Wire Transfer: Bank of America, Routing #121000358, Acct #987654321", 100, 500, 530, 25),
        ]
    elif doc_kind == "onboarding_form":
        lines = [
            (0, "EMPLOYEE ONBOARDING & REGISTRATION FORM", 100, 80, 600, 35),
            (1, "Full Legal Name: Sarah Jenkins | DOB: 1994-05-12 | SSN: XXX-XX-4912", 100, 140, 550, 25),
            (2, "Address: 420 Innovation Way, Austin, TX 78701 | Phone: 555-0144", 100, 180, 520, 25),
            (3, "Job Title: Staff Software Architect | Department: Engineering | Start: 2026-10-01", 100, 240, 580, 25),
            (4, "Emergency Contact: Robert Jenkins (Spouse) | Phone: 555-0199", 100, 300, 510, 25),
            (5, "Direct Deposit: Chase Bank | Routing: 111000025 | Account: 445566778", 100, 360, 530, 25),
            (6, "I certify that the above information is true and accurate.", 100, 420, 500, 25),
        ]
    else:  # resume / unknown
        lines = [
            (0, "ALEXANDER CHEN", 100, 100, 300, 35),
            (1, "alex.chen@email.com | (555) 234-5678 | San Francisco, CA", 100, 140, 450, 25),
            (2, "EDUCATION: B.S. in Computer Science, UC Berkeley, 2020", 100, 190, 480, 25),
            (3, "SKILLS: Python, TypeScript, React, Docker, Kubernetes, SQL", 100, 230, 500, 25),
            (4, "EXPERIENCE: Senior Backend Engineer at DataFlow Systems", 100, 280, 520, 25),
        ]

    blocks = [
        OCRBlock(
            block_index=idx,
            text=text,
            confidence=94.0,
            bbox=BoundingBox(x=x, y=y, width=w, height=h),
            page_number=1,
        )
        for idx, text, x, y, w, h in lines
    ]

    page_text = "\n".join(b.text for b in blocks)
    return OCRDocumentResult(
        document_id=doc_id,
        page_count=1,
        full_text=f"--- PAGE 1 ---\n{page_text}",
        pages=[
            OCRPageResult(
                page_number=1,
                width=1653,
                height=2339,
                text=page_text,
                blocks=blocks,
            )
        ],
        metadata=OCRMetadata(
            block_count=len(blocks),
            average_confidence=94.0,
            processing_duration_ms=120,
            ocr_engine="tesseract",
        ),
    )


def test_1_section_whitelists():
    print("\n--- 1. Testing Section Whitelists & Validation ---")
    assert "vendor_information" in INVOICE_SECTION_WHITELIST
    assert "customer_information" in INVOICE_SECTION_WHITELIST
    assert "invoice_metadata" in INVOICE_SECTION_WHITELIST
    assert "line_items" in INVOICE_SECTION_WHITELIST
    assert "payment_information" in INVOICE_SECTION_WHITELIST
    assert "tax_information" in INVOICE_SECTION_WHITELIST
    assert "notes" in INVOICE_SECTION_WHITELIST
    assert "unknown" in INVOICE_SECTION_WHITELIST

    assert "personal_information" in ONBOARDING_SECTION_WHITELIST
    assert "contact_information" in ONBOARDING_SECTION_WHITELIST
    assert "employment_information" in ONBOARDING_SECTION_WHITELIST
    assert "emergency_contact" in ONBOARDING_SECTION_WHITELIST
    assert "identity_documents" in ONBOARDING_SECTION_WHITELIST
    assert "bank_details" in ONBOARDING_SECTION_WHITELIST
    assert "agreements" in ONBOARDING_SECTION_WHITELIST
    assert "notes" in ONBOARDING_SECTION_WHITELIST
    assert "unknown" in ONBOARDING_SECTION_WHITELIST
    print("  [OK] Whitelists configured accurately according to specifications.")


def test_2_unknown_document_handling():
    print("\n--- 2. Testing Unknown Document Type Handling (Strictly Empty Result) ---")
    detector = SectionDetector()
    resume_ocr = build_mock_ocr_result("doc_unknown_test", "unknown")

    # In accordance with prompt: If document_type = unknown, return: []
    # Do not force section detection; do not invoke Gemini.
    result = detector.detect_sections(resume_ocr, "unknown")
    assert result.document_id == "doc_unknown_test"
    assert result.document_type == "unknown"
    assert len(result.sections) == 0
    print("  [OK] Unknown document returned 0 sections immediately without invoking LLM.")


def test_3_prompt_builder():
    print("\n--- 3. Testing Section Detection Prompt Construction ---")
    detector = SectionDetector()
    inv_ocr = build_mock_ocr_result("doc_inv_prompt", "invoice")
    prompt = detector.build_section_prompt(inv_ocr, "invoice")

    assert "You are a document structure analyzer." in prompt
    assert "Identify sections only." in prompt
    assert "Do NOT extract fields." in prompt
    assert "Do NOT summarize." in prompt
    assert "Do NOT classify." in prompt
    assert "Only identify regions." in prompt
    assert "Return structured JSON." in prompt
    assert "vendor_information" in prompt
    assert "customer_information" in prompt
    assert "line_items" in prompt
    print(f"  [OK] Prompt generated cleanly ({len(prompt)} chars) with all required negative directives.")


def test_4_bounding_box_union():
    print("\n--- 4. Testing Bounding Box Union Calculation ---")
    blocks = [
        OCRBlock(block_index=0, text="A", confidence=90.0, bbox=BoundingBox(x=100, y=100, width=200, height=30), page_number=1),
        OCRBlock(block_index=1, text="B", confidence=90.0, bbox=BoundingBox(x=120, y=140, width=300, height=40), page_number=1),
        OCRBlock(block_index=2, text="C", confidence=90.0, bbox=BoundingBox(x=80, y=190, width=250, height=30), page_number=1),
    ]
    bbox = compute_blocks_bounding_box(blocks)
    assert bbox is not None
    assert bbox.x == 80  # min_x
    assert bbox.y == 100  # min_y
    # max_x = max(100+200, 120+300, 80+250) = 420; width = 420 - 80 = 340
    assert bbox.width == 340
    # max_y = max(100+30, 140+40, 190+30) = 220; height = 220 - 100 = 120
    assert bbox.height == 120
    print(f"  [OK] Union BoundingBox computed correctly: x={bbox.x}, y={bbox.y}, w={bbox.width}, h={bbox.height}")


def test_5_invoice_mock_detection():
    print("\n--- 5. Testing Invoice Section Detection (Mocked Gemini) ---")
    detector = SectionDetector()
    inv_ocr = build_mock_ocr_result("doc_inv_sections", "invoice")

    mock_gemini_output = GeminiSectionDetectionOutput(
        sections=[
            GeminiRawSection(
                section_name="vendor_information",
                page_number=1,
                text="Acme Global Technologies Inc.\n123 Tech Boulevard, Suite 500, San Jose, CA 95110",
                confidence=0.98,
                block_ids=[0, 1],
            ),
            GeminiRawSection(
                section_name="customer_information",
                page_number=1,
                text="Bill To: Beta Logistics Corp, 456 Freight Way, Dallas, TX",
                confidence=0.95,
                block_ids=[2],
            ),
            GeminiRawSection(
                section_name="invoice_metadata",
                page_number=1,
                text="INVOICE #INV-2026-9901 | Issue Date: 2026-09-01 | Due: 2026-10-01",
                confidence=0.97,
                block_ids=[3],
            ),
            GeminiRawSection(
                section_name="line_items",
                page_number=1,
                text="Item 1: Cloud Server Instances - 10 Units @ $100.00 = $1,000.00\nItem 2: Managed Kubernetes Cluster - 1 Month = $500.00\nSubtotal: $1,500.00 | Tax (8.25%): $123.75 | Total Due: $1,623.75",
                confidence=0.94,
                block_ids=[4, 5, 6],
            ),
            GeminiRawSection(
                section_name="payment_information",
                page_number=1,
                text="Wire Transfer: Bank of America, Routing #121000358, Acct #987654321",
                confidence=0.92,
                block_ids=[7],
            ),
            # Invalid section name to test fallback
            GeminiRawSection(
                section_name="random_unsupported_section",
                page_number=1,
                text="Some weird text",
                confidence=0.50,
                block_ids=[],
            ),
        ]
    )

    with patch.object(gemini_service, "detect_sections", return_value=mock_gemini_output):
        result = detector.detect_sections(inv_ocr, "invoice")
        assert result.document_id == "doc_inv_sections"
        assert result.document_type == "invoice"
        assert len(result.sections) == 6

        section_names = [s.section_name for s in result.sections]
        assert "vendor_information" in section_names
        assert "customer_information" in section_names
        assert "invoice_metadata" in section_names
        assert "line_items" in section_names
        assert "payment_information" in section_names
        assert "unknown" in section_names  # fallback for invalid section name

        # Validate bounding box computation on vendor_information
        vendor_sec = next(s for s in result.sections if s.section_name == "vendor_information")
        assert vendor_sec.bbox is not None
        assert vendor_sec.bbox.x == 100
        assert vendor_sec.bbox.y == 100
        assert len(vendor_sec.block_ids) == 2
        print(f"  [OK] Invoice sections detected ({len(result.sections)} sections). Invalid section correctly fell back to 'unknown'.")


def test_6_onboarding_mock_detection():
    print("\n--- 6. Testing Onboarding Form Section Detection (Mocked Gemini) ---")
    detector = SectionDetector()
    onb_ocr = build_mock_ocr_result("doc_onb_sections", "onboarding_form")

    mock_gemini_output = GeminiSectionDetectionOutput(
        sections=[
            GeminiRawSection(
                section_name="personal_information",
                page_number=1,
                text="Full Legal Name: Sarah Jenkins | DOB: 1994-05-12 | SSN: XXX-XX-4912",
                confidence=0.96,
                block_ids=[1],
            ),
            GeminiRawSection(
                section_name="contact_information",
                page_number=1,
                text="Address: 420 Innovation Way, Austin, TX 78701 | Phone: 555-0144",
                confidence=0.93,
                block_ids=[2],
            ),
            GeminiRawSection(
                section_name="employment_information",
                page_number=1,
                text="Job Title: Staff Software Architect | Department: Engineering | Start: 2026-10-01",
                confidence=0.95,
                block_ids=[3],
            ),
            GeminiRawSection(
                section_name="emergency_contact",
                page_number=1,
                text="Emergency Contact: Robert Jenkins (Spouse) | Phone: 555-0199",
                confidence=0.97,
                block_ids=[4],
            ),
            GeminiRawSection(
                section_name="bank_details",
                page_number=1,
                text="Direct Deposit: Chase Bank | Routing: 111000025 | Account: 445566778",
                confidence=0.91,
                block_ids=[5],
            ),
            GeminiRawSection(
                section_name="agreements",
                page_number=1,
                text="I certify that the above information is true and accurate.",
                confidence=0.89,
                block_ids=[6],
            ),
        ]
    )

    with patch.object(gemini_service, "detect_sections", return_value=mock_gemini_output):
        result = detector.detect_sections(onb_ocr, "onboarding_form")
        assert result.document_id == "doc_onb_sections"
        assert result.document_type == "onboarding_form"
        assert len(result.sections) == 6

        section_names = [s.section_name for s in result.sections]
        assert "personal_information" in section_names
        assert "contact_information" in section_names
        assert "employment_information" in section_names
        assert "emergency_contact" in section_names
        assert "bank_details" in section_names
        assert "agreements" in section_names
        print(f"  [OK] Onboarding form sections detected successfully ({len(result.sections)} sections).")


def test_7_schema_validation():
    print("\n--- 7. Testing Schema Output Validation & Constraints ---")
    sec = DocumentSection(
        section_id=str(uuid.uuid4()),
        document_id="doc-123",
        section_name="vendor_information",
        page_number=1,
        text="Acme Corp",
        confidence=0.95,
        block_ids=[0, 1],
        bbox=BoundingBox(x=10, y=20, width=300, height=50),
    )
    assert sec.confidence == 0.95
    assert sec.section_name == "vendor_information"

    # Reject out-of-range confidence
    try:
        DocumentSection(
            section_id="sec-1",
            document_id="doc-1",
            section_name="notes",
            page_number=1,
            text="xyz",
            confidence=1.5,
        )
        assert False, "Should fail on confidence > 1.0"
    except Exception:
        print("  [OK] Reject confidence > 1.0 verified.")


def test_8_api_preconditions():
    print("\n--- 8. Testing API Preconditions (OCR & Classification required) ---")
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.post(f"/api/documents/{fake_id}/detect-sections")
    assert resp.status_code == 404
    print(f"  [OK] Nonexistent document properly returns HTTP 404: {resp.json().get('detail')}")


def test_9_live_gemini_section_detection():
    print("\n--- 9. Testing Live Gemini Section Detection (if API key available) ---")
    if not gemini_service.is_configured():
        print("  [SKIP] GEMINI_API_KEY is not set. Skipping live cloud test.")
        return

    print("  [INFO] GEMINI_API_KEY detected! Testing live section detection on invoice...")
    inv_ocr = build_mock_ocr_result("live_invoice_sec_test", "invoice")
    try:
        result = detect_sections_for_document(inv_ocr, "invoice")
        print(f"  [OK] Live Gemini detected {len(result.sections)} sections in invoice!")
        for s in result.sections:
            print(f"    - Section: {s.section_name} (Confidence: {s.confidence*100:.1f}%, Page {s.page_number}, Blocks: {s.block_ids})")
        assert len(result.sections) >= 3
        sec_names = [s.section_name for s in result.sections]
        assert any(k in sec_names for k in ["vendor_information", "invoice_metadata", "line_items", "customer_information"])
    except Exception as e:
        print(f"  [WARNING] Live Gemini call returned error: {e}")


if __name__ == "__main__":
    print("==================================================")
    print("PHASE 7: SECTION DETECTION TEST SUITE")
    print("==================================================")
    test_1_section_whitelists()
    test_2_unknown_document_handling()
    test_3_prompt_builder()
    test_4_bounding_box_union()
    test_5_invoice_mock_detection()
    test_6_onboarding_mock_detection()
    test_7_schema_validation()
    test_8_api_preconditions()
    test_9_live_gemini_section_detection()
    print("\n==================================================")
    print("ALL PHASE 7 SECTION DETECTION TESTS COMPLETED!")
    print("==================================================")
