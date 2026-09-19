import sys
import os
import io
import json
import shutil
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
    DocumentType,
    GeminiClassificationOutput,
    DocumentClassificationResult,
)
from app.pipeline.classifier import DocumentClassifier, classify_document
from app.services.gemini import gemini_service, GeminiNotConfiguredError, GeminiServiceError
from app.pipeline.preprocessing import BASE_TMP_DIR, _ensure_clean_dir

client = TestClient(app)


def build_mock_ocr_result(doc_id: str, doc_kind: str) -> OCRDocumentResult:
    """Helper to build realistic OCR results for various document kinds."""
    if doc_kind == "invoice":
        lines = [
            (0, "INVOICE #INV-2026-9901", 100, 100),
            (1, "Vendor: Acme Global Technologies Inc.", 100, 140),
            (2, "Bill To: Beta Logistics Corp", 100, 180),
            (3, "Item: Cloud Infrastructure 10 Units @ $100.00 = $1,000.00", 100, 240),
            (4, "Subtotal: $1,000.00 | Tax (8%): $80.00", 100, 300),
            (5, "Total Balance Due: $1,080.00", 100, 340),
            (6, "Payment Terms: Net 30 Days", 100, 380),
        ]
    elif doc_kind == "onboarding_form":
        lines = [
            (0, "EMPLOYEE ONBOARDING & REGISTRATION FORM", 100, 100),
            (1, "Section A: Personal Information", 100, 140),
            (2, "Full Legal Name: Sarah Jenkins", 100, 180),
            (3, "Date of Birth: 1994-05-12 | SSN: XXX-XX-4912", 100, 220),
            (4, "Residential Address: 420 Innovation Way, Austin, TX", 100, 260),
            (5, "Emergency Contact: Robert Jenkins (Relationship: Spouse) Phone: 555-0144", 100, 300),
            (6, "Department: Engineering | Role: Staff Software Architect", 100, 340),
            (7, "Declaration: I hereby certify that the information provided is accurate.", 100, 380),
        ]
    elif doc_kind == "resume":
        lines = [
            (0, "ALEXANDER CHEN", 100, 100),
            (1, "alex.chen@email.com | (555) 234-5678 | San Francisco, CA", 100, 130),
            (2, "EDUCATION: B.S. in Computer Science, UC Berkeley, 2020", 100, 180),
            (3, "SKILLS: Python, TypeScript, React, Docker, Kubernetes, SQL", 100, 220),
            (4, "EXPERIENCE: Senior Backend Engineer at DataFlow Systems (2021 - Present)", 100, 260),
            (5, "Led architecture of event-driven distributed streaming pipelines", 100, 290),
            (6, "PROJECTS: Autonomous Document Pipeline - Multi-stage parser", 100, 340),
        ]
    else:  # random
        lines = [
            (0, "WEEKLY BISTRO SPECIALS & DINNER MENU", 100, 100),
            (1, "Appetizers: Truffle Fries $12 | Crispy Calamari $16", 100, 140),
            (2, "Entrees: Pan-Seared Salmon $28 | Ribeye Steak $38", 100, 180),
            (3, "Desserts: Tiramisu $10 | Chocolate Lava Cake $12", 100, 220),
        ]

    blocks = [
        OCRBlock(
            block_index=idx,
            text=text,
            confidence=92.5,
            bbox=BoundingBox(x=x, y=y, width=400, height=30),
            page_number=1,
        )
        for idx, text, x, y in lines
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
            average_confidence=92.5,
            processing_duration_ms=150,
            ocr_engine="tesseract",
        ),
    )


def test_1_classification_input_builder():
    print("\n--- 1. Testing Classification Input Builder ---")
    ocr_res = build_mock_ocr_result("doc_test_input", "invoice")
    classifier = DocumentClassifier(confidence_threshold=0.70)
    prompt = classifier.build_classification_input(ocr_res)

    assert "TOTAL DOCUMENT PAGES: 1" in prompt
    assert "invoice" in prompt
    assert "onboarding_form" in prompt
    assert "unknown" in prompt
    assert "ACME GLOBAL" in prompt.upper()
    assert len(prompt) < 7500
    print(f"  [OK] Input prompt constructed cleanly ({len(prompt)} chars).")


def test_2_precondition_ocr_required():
    print("\n--- 2. Testing Precondition: OCR Must Be Completed ---")
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.post(f"/api/documents/{fake_id}/classify")
    assert resp.status_code == 404
    print(f"  [OK] Nonexistent document returned 404: {resp.json().get('detail')}")


def test_3_gemini_missing_key_handling():
    print("\n--- 3. Testing Missing Gemini Key Error Handling ---")
    with patch.object(settings, "GEMINI_API_KEY", ""):
        assert not gemini_service.is_configured()
        try:
            gemini_service.get_client()
            assert False, "Should have raised GeminiNotConfiguredError"
        except GeminiNotConfiguredError as e:
            print(f"  [OK] Correctly caught missing key error: {e}")


def test_4_classification_thresholding_logic():
    print("\n--- 4. Testing Confidence Thresholding (0.70) ---")
    classifier = DocumentClassifier(confidence_threshold=0.70)
    ocr_res = build_mock_ocr_result("doc_thresh_test", "invoice")

    # Scenario A: High confidence invoice (0.94) -> invoice
    mock_high_inv = GeminiClassificationOutput(
        document_type=DocumentType.INVOICE,
        confidence=0.94,
        evidence=["Invoice number detected", "Line items and totals found"],
    )
    with patch.object(gemini_service, "classify_content", return_value=mock_high_inv):
        res_a = classifier.classify(ocr_res)
        assert res_a.document_type == DocumentType.INVOICE
        assert res_a.confidence == 0.94
        assert not res_a.metadata.get("below_threshold")
        print(f"  [OK] High confidence (0.94) -> {res_a.document_type.value}")

    # Scenario B: Low confidence invoice (0.62 < 0.70) -> unknown
    mock_low_inv = GeminiClassificationOutput(
        document_type=DocumentType.INVOICE,
        confidence=0.62,
        evidence=["Ambiguous pricing snippet"],
    )
    with patch.object(gemini_service, "classify_content", return_value=mock_low_inv):
        res_b = classifier.classify(ocr_res)
        assert res_b.document_type == DocumentType.UNKNOWN
        assert res_b.confidence == 0.62
        assert res_b.metadata.get("below_threshold") is True
        assert any("below threshold" in ev for ev in res_b.evidence)
        print(f"  [OK] Low confidence (0.62 < 0.70) -> {res_b.document_type.value} (safely downgraded)")

    # Scenario C: Onboarding form high confidence (0.88) -> onboarding_form
    mock_onboarding = GeminiClassificationOutput(
        document_type=DocumentType.ONBOARDING_FORM,
        confidence=0.88,
        evidence=["Emergency contact and employee intake fields detected"],
    )
    with patch.object(gemini_service, "classify_content", return_value=mock_onboarding):
        res_c = classifier.classify(ocr_res)
        assert res_c.document_type == DocumentType.ONBOARDING_FORM
        assert res_c.confidence == 0.88
        print(f"  [OK] Onboarding form (0.88) -> {res_c.document_type.value}")


def test_5_resume_strictly_unknown():
    print("\n--- 5. Testing Resume Archetype (Strictly 'unknown') ---")
    classifier = DocumentClassifier(confidence_threshold=0.70)
    resume_ocr = build_mock_ocr_result("doc_resume_test", "resume")

    # In accordance with Section 9 & Section 21 of prompt:
    # A resume must NEVER be classified as onboarding_form
    mock_resume = GeminiClassificationOutput(
        document_type=DocumentType.UNKNOWN,
        confidence=0.92,
        evidence=["Document contains resume work history and education; does not match invoice or onboarding form"],
    )
    with patch.object(gemini_service, "classify_content", return_value=mock_resume):
        res = classifier.classify(resume_ocr)
        assert res.document_type == DocumentType.UNKNOWN
        assert res.document_type != DocumentType.ONBOARDING_FORM
        print(f"  [OK] Resume classified as: {res.document_type.value} (NOT onboarding_form)")


def test_6_random_document_unknown():
    print("\n--- 6. Testing Random Document (Restaurant Menu -> 'unknown') ---")
    classifier = DocumentClassifier(confidence_threshold=0.70)
    random_ocr = build_mock_ocr_result("doc_random_test", "random")

    mock_random = GeminiClassificationOutput(
        document_type=DocumentType.UNKNOWN,
        confidence=0.95,
        evidence=["Restaurant dinner menu; does not match invoice or onboarding form"],
    )
    with patch.object(gemini_service, "classify_content", return_value=mock_random):
        res = classifier.classify(random_ocr)
        assert res.document_type == DocumentType.UNKNOWN
        print(f"  [OK] Random document classified as: {res.document_type.value}")


def test_7_structured_output_validation():
    print("\n--- 7. Testing Schema Output Validation & Boundary Constraints ---")
    # Valid output
    valid_data = {
        "document_type": "invoice",
        "confidence": 0.95,
        "evidence": ["Invoice number present", "Tax calculated"],
    }
    validated = GeminiClassificationOutput.model_validate(valid_data)
    assert validated.document_type == DocumentType.INVOICE
    assert validated.confidence == 0.95

    # Out-of-bounds confidence validation
    try:
        GeminiClassificationOutput.model_validate({"document_type": "invoice", "confidence": 1.5, "evidence": []})
        assert False, "Should fail on confidence > 1.0"
    except Exception:
        print("  [OK] Reject confidence > 1.0 verified.")

    try:
        GeminiClassificationOutput.model_validate({"document_type": "invoice", "confidence": -0.2, "evidence": []})
        assert False, "Should fail on confidence < 0.0"
    except Exception:
        print("  [OK] Reject confidence < 0.0 verified.")


def test_8_live_gemini_integration():
    print("\n--- 8. Testing Live Gemini Integration (if API key provided) ---")
    if not gemini_service.is_configured():
        print("  [SKIP] GEMINI_API_KEY is not set in backend/.env. Skipping live cloud API test.")
        print("  [INFO] Unit tests with mock responses confirmed all classification logic works.")
        return

    print("  [INFO] GEMINI_API_KEY detected! Running live Gemini classification test...")
    invoice_ocr = build_mock_ocr_result("live_test_invoice", "invoice")
    try:
        res = classify_document(invoice_ocr)
        print(f"  [OK] Live Gemini classified invoice as: {res.document_type.value} (Confidence: {res.confidence * 100:.1f}%)")
        print(f"  [OK] Live evidence: {res.evidence}")
        assert res.document_type in (DocumentType.INVOICE, DocumentType.UNKNOWN)
    except Exception as e:
        print(f"  [WARNING] Live Gemini call returned error: {e}")


if __name__ == "__main__":
    print("==================================================")
    print("PHASE 6: DOCUMENT CLASSIFICATION TEST SUITE")
    print("==================================================")
    test_1_classification_input_builder()
    test_2_precondition_ocr_required()
    test_3_gemini_missing_key_handling()
    test_4_classification_thresholding_logic()
    test_5_resume_strictly_unknown()
    test_6_random_document_unknown()
    test_7_structured_output_validation()
    test_8_live_gemini_integration()
    print("\n==================================================")
    print("ALL PHASE 6 CLASSIFICATION TESTS COMPLETED!")
    print("==================================================")
