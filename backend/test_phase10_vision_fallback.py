"""
Comprehensive Automated Test Suite for Phase 10:
Low-Confidence & Handwriting Vision Fallback

Covers 12 distinct test scenarios:
1. High confidence field bypasses vision.
2. Low confidence field triggers vision fallback.
3. Empty OCR field triggers vision fallback.
4. OCR + Vision agree -> action 'agreed', status valid.
5. OCR + Vision disagree -> action 'conflict', status conflict.
6. Unreadable handwriting returns null -> action 'unreadable', status needs_review.
7. High confidence OCR with math discrepancy does not trigger vision.
8. Targeted crop boundary clamping & context padding (+25px).
9. Rerun idempotency (fallback_attempted flag prevents repeat vision calls).
10. Automatic re-normalization & re-validation after vision recovery.
11. FastAPI TestClient endpoints (POST and GET /api/documents/{id}/vision-fallback).
12. Live Gemini Vision multimodal call on cropped test image with PIL.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.pipeline.types import (
    BoundingBox,
    DocumentValidationResult,
    DocumentValidationSummary,
    DocumentVisionFallbackResult,
    ExtractedField,
    GeminiVisionRecoveryOutput,
    ValidationStatusEnum,
    VisionFallbackFieldResult,
)
from app.pipeline.normalizer import FieldNormalizer
from app.pipeline.validator import DocumentValidator
from app.pipeline.vision_fallback import VisionFallbackManager, values_agree
from app.services.gemini import gemini_service


class MockGeminiService:
    """Mock GeminiService for deterministic test assertions."""

    def __init__(self, mock_output: GeminiVisionRecoveryOutput = None):
        self.mock_output = mock_output
        self.calls = []

    def is_configured(self) -> bool:
        return True

    def recover_field_vision(self, image, prompt, model=None):
        self.calls.append({"image_size": image.size, "prompt": prompt})
        if self.mock_output:
            return self.mock_output
        return GeminiVisionRecoveryOutput(
            field_name="test_field",
            value="Recovered Value",
            confidence=0.92,
            source_text="Visible test label",
            reason="Clear text visible in crop",
        )


class TestPhase10VisionFallback(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.doc_id = "test-doc-phase10-uuid"
        self.doc_dir = self.temp_dir / self.doc_id
        self.doc_dir.mkdir(parents=True, exist_ok=True)

        # Create a dummy test image for page_001.png
        img = Image.new("RGB", (800, 1000), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Draw some mock text lines
        draw.text((50, 50), "INVOICE # INV-2024-999", fill=(0, 0, 0))
        draw.text((50, 100), "Date: 15/03/2024", fill=(0, 0, 0))
        draw.text((50, 150), "Total: INR 1,500.00", fill=(0, 0, 0))
        draw.text((50, 200), "Vendor: Acme Corp", fill=(0, 0, 0))
        img.save(self.doc_dir / "page_001.png")

        # Mock OCR output
        ocr_data = {
            "document_id": self.doc_id,
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "width": 800,
                    "height": 1000,
                    "blocks": [
                        {
                            "block_index": 0,
                            "text": "INVOICE # INV-2024-999",
                            "confidence": 95.0,
                            "bbox": {"x": 50, "y": 50, "width": 250, "height": 30},
                            "page_number": 1,
                        },
                        {
                            "block_index": 1,
                            "text": "Date: 15/03/2024",
                            "confidence": 42.0,
                            "bbox": {"x": 50, "y": 100, "width": 200, "height": 30},
                            "page_number": 1,
                        },
                        {
                            "block_index": 2,
                            "text": "Total: INR 1,500.00",
                            "confidence": 88.0,
                            "bbox": {"x": 50, "y": 150, "width": 220, "height": 30},
                            "page_number": 1,
                        },
                    ],
                }
            ],
            "metadata": {"block_count": 3, "average_confidence": 75.0, "ocr_engine": "tesseract"},
        }
        with open(self.doc_dir / "ocr_result.json", "w", encoding="utf-8") as f:
            json.dump(ocr_data, f)

        # Mock Sections
        sections_data = {
            "document_id": self.doc_id,
            "document_type": "invoice",
            "sections": [
                {
                    "section_id": "sec-1",
                    "document_id": self.doc_id,
                    "section_name": "invoice_metadata",
                    "page_number": 1,
                    "text": "INVOICE # INV-2024-999\nDate: 15/03/2024",
                    "confidence": 0.95,
                    "block_ids": [0, 1],
                    "bbox": {"x": 45, "y": 45, "width": 260, "height": 90},
                },
                {
                    "section_id": "sec-2",
                    "document_id": self.doc_id,
                    "section_name": "tax_and_totals",
                    "page_number": 1,
                    "text": "Total: INR 1,500.00",
                    "confidence": 0.95,
                    "block_ids": [2],
                    "bbox": {"x": 45, "y": 145, "width": 230, "height": 40},
                },
            ],
        }
        with open(self.doc_dir / "sections.json", "w", encoding="utf-8") as f:
            json.dump(sections_data, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --- Test 1: High confidence field bypasses vision ---
    def test_01_high_confidence_bypasses_vision(self):
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir)
        field = ExtractedField(
            field_name="invoice_number",
            field_value="INV-2024-999",
            confidence=0.96,
            section_name="invoice_metadata",
            page_number=1,
            validation_status="valid",
        )
        candidates = manager.identify_candidates([field])
        self.assertEqual(len(candidates), 0, "High confidence valid field should not be a fallback candidate")

    # --- Test 2: Low confidence field triggers vision ---
    def test_02_low_confidence_triggers_vision(self):
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir)
        field = ExtractedField(
            field_name="invoice_date",
            field_value="15/03/2024",
            confidence=0.45,  # Below 0.70 threshold
            section_name="invoice_metadata",
            page_number=1,
            validation_status="valid",
        )
        candidates = manager.identify_candidates([field])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0].field_name, "invoice_date")
        self.assertIn("Low OCR confidence", candidates[0][1])

    # --- Test 3: Empty OCR field triggers vision ---
    def test_03_empty_ocr_field_triggers_vision(self):
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir)
        field = ExtractedField(
            field_name="vendor_name",
            field_value=None,
            confidence=None,
            section_name="vendor_information",
            page_number=1,
            validation_status="needs_review",
            validation_message="Required invoice field 'vendor_name' is missing.",
        )
        candidates = manager.identify_candidates([field])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0].field_name, "vendor_name")
        self.assertIn("Missing value flagged", candidates[0][1])

    # --- Test 4: OCR + Vision agree -> action 'agreed' ---
    def test_04_ocr_vision_agree(self):
        mock_gemini = MockGeminiService(
            GeminiVisionRecoveryOutput(
                field_name="invoice_number",
                value="INV-2024-999",
                confidence=0.98,
                source_text="INVOICE # INV-2024-999",
                reason="Clear printed invoice number visible",
            )
        )
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir, gemini=mock_gemini)
        field = ExtractedField(
            field_name="invoice_number",
            field_value="INV-2024-999",
            confidence=0.55,
            section_name="invoice_metadata",
            source_text="INVOICE # INV-2024-999",
            page_number=1,
        )
        res = manager.evaluate_recovery(field, mock_gemini.mock_output, "Low OCR confidence")
        self.assertEqual(res.action_taken, "agreed")
        self.assertEqual(field.source, "ocr+vision")
        self.assertGreaterEqual(field.confidence, 0.90)
        self.assertEqual(field.ocr_value, "INV-2024-999")
        self.assertEqual(field.vision_value, "INV-2024-999")

    # --- Test 5: OCR + Vision disagree -> action 'conflict' ---
    def test_05_ocr_vision_conflict(self):
        mock_gemini = MockGeminiService(
            GeminiVisionRecoveryOutput(
                field_name="invoice_number",
                value="INV-2024-888",
                confidence=0.95,
                source_text="INVOICE # INV-2024-888",
                reason="Visible 888, not 999",
            )
        )
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir, gemini=mock_gemini)
        field = ExtractedField(
            field_name="invoice_number",
            field_value="INV-2024-999",
            confidence=0.92,
            section_name="invoice_metadata",
            page_number=1,
        )
        res = manager.evaluate_recovery(field, mock_gemini.mock_output, "OCR format check")
        self.assertEqual(res.action_taken, "conflict")
        self.assertEqual(field.validation_status, ValidationStatusEnum.CONFLICT.value)
        self.assertIn("Conflict between OCR", field.validation_message)

    # --- Test 6: Unreadable handwriting returns null -> action 'unreadable' ---
    def test_06_unreadable_handwriting_returns_null(self):
        mock_gemini = MockGeminiService(
            GeminiVisionRecoveryOutput(
                field_name="customer_notes",
                value=None,
                confidence=0.10,
                source_text=None,
                reason="Illegible cursive script and heavy ink smudge",
            )
        )
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir, gemini=mock_gemini)
        field = ExtractedField(
            field_name="customer_notes",
            field_value="?? smudged",
            confidence=0.20,
            section_name="notes",
            page_number=1,
        )
        res = manager.evaluate_recovery(field, mock_gemini.mock_output, "Low OCR confidence")
        self.assertEqual(res.action_taken, "unreadable")
        self.assertEqual(field.validation_status, ValidationStatusEnum.NEEDS_REVIEW.value)
        self.assertIn("unreadable in visual crop", field.validation_message)

    # --- Test 7: High confidence OCR with math discrepancy does not trigger vision ---
    def test_07_math_discrepancy_does_not_trigger_vision(self):
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir)
        field = ExtractedField(
            field_name="total",
            field_value="1500.00",
            confidence=0.95,
            section_name="tax_and_totals",
            page_number=1,
            validation_status="needs_review",
            validation_message="Math discrepancy: Total (1500.00) does not match calculated (1400.00).",
        )
        candidates = manager.identify_candidates([field])
        self.assertEqual(len(candidates), 0, "High confidence field with arithmetic mismatch should not call vision AI")

    # --- Test 8: Targeted crop boundary clamping & context padding ---
    def test_08_crop_clamping_and_padding(self):
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir)
        # Bounding box near corner: x=5, y=5, width=40, height=30
        bbox = BoundingBox(x=5, y=5, width=40, height=30)
        crop_res = manager.crop_image(self.doc_id, page_number=1, bbox=bbox, padding=25)
        self.assertIsNotNone(crop_res)
        cropped_img, clamped_bbox = crop_res

        # Padding 25 should clamp x_min to 0 and y_min to 0
        self.assertEqual(clamped_bbox.x, 0)
        self.assertEqual(clamped_bbox.y, 0)
        self.assertEqual(clamped_bbox.width, 5 + 40 + 25)
        self.assertEqual(clamped_bbox.height, 5 + 30 + 25)
        self.assertEqual(cropped_img.size, (clamped_bbox.width, clamped_bbox.height))

    # --- Test 9: Rerun idempotency ---
    def test_09_rerun_idempotency(self):
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir)
        field = ExtractedField(
            field_name="invoice_date",
            field_value="15/03/2024",
            confidence=0.40,
            section_name="invoice_metadata",
            page_number=1,
            fallback_attempted=True,  # Already attempted
            fallback_reason="Previously attempted",
        )
        candidates = manager.identify_candidates([field])
        self.assertEqual(len(candidates), 0, "Already attempted field must be skipped to avoid duplicate billing")

    # --- Test 10: Automatic re-normalization & re-validation ---
    def test_10_automatic_renormalization_and_revalidation(self):
        mock_gemini = MockGeminiService(
            GeminiVisionRecoveryOutput(
                field_name="invoice_date",
                value="15/03/2024",
                confidence=0.96,
                source_text="Date: 15/03/2024",
                reason="Clearly reads 15/03/2024",
            )
        )
        manager = VisionFallbackManager(processing_base_dir=self.temp_dir, gemini=mock_gemini)

        # Field had low confidence
        date_field = ExtractedField(
            field_name="invoice_date",
            field_value="15/03/2024",
            confidence=0.35,
            section_name="invoice_metadata",
            source_text="Date: 15/03/2024",
            page_number=1,
        )
        num_field = ExtractedField(
            field_name="invoice_number",
            field_value="INV-2024-999",
            confidence=0.98,
            section_name="invoice_metadata",
            source_text="INVOICE # INV-2024-999",
            page_number=1,
        )

        result = manager.execute_fallback(
            document_id=self.doc_id,
            document_type="invoice",
            fields=[date_field, num_field],
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.candidates_identified, 1)
        self.assertEqual(result.fields_recovered + sum(1 for f in result.fallback_fields if f.action_taken == "agreed"), 1)
        self.assertIsNotNone(result.updated_validation)
        # Verify normalized value was computed
        self.assertEqual(date_field.normalized_value, "2024-03-15")
        self.assertTrue((self.doc_dir / "vision_fallback.json").exists())

    # --- Test 11: FastAPI TestClient endpoints ---
    def test_11_fastapi_endpoints(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        from app.main import app

        client = TestClient(app)

        # Mock database lookup for document
        mock_doc = {
            "id": self.doc_id,
            "filename": "test_invoice.pdf",
            "document_type": "invoice",
            "status": "extracted",
        }

        with patch("app.services.supabase.supabase_service.is_configured", return_value=True), \
             patch("app.services.supabase.supabase_service.get_document", return_value=mock_doc), \
             patch("app.services.supabase.supabase_service.create_processing_log", return_value=True), \
             patch("app.services.supabase.supabase_service.save_validated_fields", return_value=True), \
             patch("app.services.supabase.supabase_service.update_document_status", return_value=True), \
             patch("app.services.gemini.gemini_service.is_configured", return_value=True), \
             patch("app.pipeline.vision_fallback.vision_fallback_manager.base_dir", self.temp_dir), \
             patch("app.api.documents.BASE_TMP_DIR", str(self.temp_dir)):

            # Seed a validation.json in temp dir
            val_data = {
                "document_id": self.doc_id,
                "document_type": "invoice",
                "document_status": "needs_review",
                "summary": {"total_fields": 2, "valid_count": 1, "needs_review_count": 1, "conflict_count": 0},
                "fields": [
                    {
                        "field_name": "invoice_date",
                        "field_value": "15/03/2024",
                        "confidence": 0.40,
                        "section_name": "invoice_metadata",
                        "page_number": 1,
                        "source_text": "Date: 15/03/2024",
                    }
                ],
                "validation_issues": [],
                "validated_at": "2026-09-20T10:00:00Z",
                "metadata": {},
            }
            with open(self.doc_dir / "validation.json", "w", encoding="utf-8") as f:
                json.dump(val_data, f)

            # Test POST /api/documents/{id}/vision-fallback
            with patch.object(
                VisionFallbackManager,
                "crop_image",
                return_value=(Image.new("RGB", (100, 50), color=(255, 255, 255)), BoundingBox(x=0, y=0, width=100, height=50))
            ), patch.object(
                gemini_service,
                "recover_field_vision",
                return_value=GeminiVisionRecoveryOutput(
                    field_name="invoice_date",
                    value="15/03/2024",
                    confidence=0.95,
                    source_text="15/03/2024",
                    reason="Clear visual date",
                )
            ):
                post_resp = client.post(f"/api/documents/{self.doc_id}/vision-fallback")
                self.assertEqual(post_resp.status_code, 200)
                post_json = post_resp.json()
                self.assertEqual(post_json["document_id"], self.doc_id)
                self.assertEqual(post_json["status"], "completed")

            # Test GET /api/documents/{id}/vision-fallback
            get_resp = client.get(f"/api/documents/{self.doc_id}/vision-fallback")
            self.assertEqual(get_resp.status_code, 200)
            get_json = get_resp.json()
            self.assertEqual(get_json["document_id"], self.doc_id)
            self.assertIn("fallback_fields", get_json)

    # --- Test 12: Live Gemini Vision multimodal call on image crop ---
    def test_12_live_gemini_vision_call(self):
        if not gemini_service.is_configured():
            self.skipTest("GEMINI_API_KEY is not configured; skipping live Gemini Vision API test.")

        # Create a tiny test crop image with clear printed text
        crop_img = Image.new("RGB", (300, 80), color=(255, 255, 255))
        draw = ImageDraw.Draw(crop_img)
        draw.text((20, 25), "INV-88291", fill=(0, 0, 0))

        prompt = """You are an expert handwriting and degraded document text recovery AI.
Inspect this image crop and extract the field 'invoice_number'.
Anti-hallucination: Only output characters clearly visible. If unreadable, return null."""

        result = gemini_service.recover_field_vision(image=crop_img, prompt=prompt)
        self.assertIsInstance(result, GeminiVisionRecoveryOutput)
        self.assertEqual(result.field_name, "invoice_number")
        self.assertIsNotNone(result.value)
        self.assertIn("88291", result.value)
        self.assertGreaterEqual(result.confidence, 0.70)


if __name__ == "__main__":
    unittest.main(verbosity=2)
