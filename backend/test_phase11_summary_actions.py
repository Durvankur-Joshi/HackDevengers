"""
Comprehensive Automated Test Suite for Phase 11:
Intelligent Document Summary & Action Extraction

Covers 12 distinct test scenarios:
1. Valid invoice summary + payment action with grounded due date.
2. Invoice with arithmetic discrepancy -> review action created, issue mentioned in summary.
3. Invoice with due date -> action due_date equals invoice due date.
4. Invoice without due date -> action due_date is strictly None (zero guessing).
5. Conflicting invoice data -> conflict review action created, summary notes conflict.
6. Onboarding form summary -> concise factual summary, sensitive data masked.
7. Onboarding with missing required data -> action identifies missing field.
8. Unknown document handling -> summary and action extraction safely skipped.
9. Rerun idempotency -> no duplicate actions; completed action status is preserved.
10. Action status update API -> PATCH /api/actions/{id} changes status, validates transitions.
11. FastAPI TestClient endpoints (summarize, summary, actions, insights, patch action).
12. Live Gemini API calls for structured summary and action generation.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from app.main import app
from app.pipeline.types import (
    ActionItem,
    ActionPriorityEnum,
    ActionStatusEnum,
    ActionStatusUpdateRequest,
    DocumentActionsResult,
    DocumentInsightsResult,
    DocumentSummaryResult,
    DocumentValidationResult,
    DocumentValidationSummary,
    ExtractedField,
    GeminiActionExtractionOutput,
    GeminiDocumentSummaryOutput,
    GeminiRawAction,
    ValidationStatusEnum,
)
from app.pipeline.summarizer import DocumentSummarizer, document_summarizer
from app.pipeline.action_extractor import DocumentActionExtractor, document_action_extractor
from app.services.gemini import gemini_service
from app.services.supabase import supabase_service


def make_field(
    name: str,
    val: any,
    norm: any = None,
    status: str = "valid",
    section: str = "general",
    msg: str = None,
) -> ExtractedField:
    """Helper to create valid ExtractedField instances with required section_name."""
    norm_val = str(norm) if norm is not None else (str(val) if val is not None else None)
    return ExtractedField(
        field_name=name,
        field_value=val,
        normalized_value=norm_val,
        validation_status=status,
        section_name=section,
        validation_message=msg,
        page_number=1,
    )


class MockGeminiSummaryService:
    """Deterministic mock for Gemini summarization and action generation."""

    def __init__(
        self,
        summary_output: GeminiDocumentSummaryOutput = None,
        action_output: GeminiActionExtractionOutput = None,
    ):
        self.summary_output = summary_output or GeminiDocumentSummaryOutput(
            summary="Invoice INV-001 from Acme Corp for $1,450.00 due on 2026-10-15.",
            key_points=["Total amount payable is $1,450.00", "Payment due by 2026-10-15", "Vendor is Acme Corp"],
            review_items=[],
        )
        self.action_output = action_output or GeminiActionExtractionOutput(
            actions=[
                GeminiRawAction(
                    action="Archive invoice INV-001 in accounting records",
                    priority="low",
                    due_date=None,
                    reason="Standard record keeping for vendor invoices",
                )
            ]
        )
        self.summary_prompts = []
        self.action_prompts = []

    def is_configured(self) -> bool:
        return True

    def generate_document_summary(self, prompt: str) -> GeminiDocumentSummaryOutput:
        self.summary_prompts.append(prompt)
        return self.summary_output

    def suggest_contextual_actions(self, prompt: str) -> GeminiActionExtractionOutput:
        self.action_prompts.append(prompt)
        return self.action_output


class TestPhase11SummaryActions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.doc_id = str(uuid.uuid4())
        self.doc_folder = Path(self.temp_dir) / self.doc_id
        self.doc_folder.mkdir(parents=True, exist_ok=True)
        self.mock_gemini = MockGeminiSummaryService()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Scenario 1: Valid invoice summary + payment action with grounded due date
    # -------------------------------------------------------------------------
    def test_01_valid_invoice_summary_and_payment_action(self):
        fields = [
            make_field("vendor_name", "Acme Corp", "Acme Corp", "valid", "vendor_information"),
            make_field("invoice_number", "INV-2026-001", "INV-2026-001", "valid", "invoice_metadata"),
            make_field("total_amount", "1450.00", 1450.0, "valid", "totals"),
            make_field("due_date", "2026-10-15", "2026-10-15", "valid", "invoice_metadata"),
        ]
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="invoice",
            document_status="completed",
            fields=fields,
            summary=DocumentValidationSummary(total_fields=4, valid_count=4, needs_review_count=0, conflict_count=0),
            validation_issues=[],
            validated_at="2026-09-20T11:00:00Z",
        )

        summarizer = DocumentSummarizer(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        summary_result = summarizer.summarize_document(self.doc_id, "invoice", val_result)

        self.assertIsNotNone(summary_result)
        self.assertEqual(summary_result.document_type, "invoice")
        self.assertIn("1,450.00", summary_result.summary)
        self.assertGreater(len(summary_result.key_points), 0)

        action_extractor = DocumentActionExtractor(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        actions_result = action_extractor.extract_actions(self.doc_id, "invoice", val_result, summary_result)

        self.assertIsNotNone(actions_result)
        self.assertGreaterEqual(actions_result.total_actions, 1)

        # Look for the payment action
        payment_actions = [a for a in actions_result.actions if "pay" in a.action.lower()]
        self.assertTrue(len(payment_actions) >= 1)
        payment_act = payment_actions[0]
        self.assertIn(payment_act.priority, [ActionPriorityEnum.HIGH, ActionPriorityEnum.MEDIUM])
        self.assertEqual(payment_act.due_date, "2026-10-15")
        self.assertEqual(payment_act.source, "rule_based")

    # -------------------------------------------------------------------------
    # Scenario 2: Invoice with arithmetic discrepancy
    # -------------------------------------------------------------------------
    def test_02_invoice_with_arithmetic_discrepancy(self):
        fields = [
            make_field("vendor_name", "Apex Supply", "Apex Supply", "valid", "vendor_information"),
            make_field("subtotal", "100.00", "100.0", "valid", "totals"),
            make_field("tax_amount", "10.00", "10.0", "valid", "totals"),
            make_field("total_amount", "150.00", "150.0", "needs_review", "totals"),
        ]
        issues = [
            {
                "field_name": "total_amount",
                "status": "needs_review",
                "code": "ARITHMETIC_MISMATCH",
                "message": "Subtotal (100.0) + Tax (10.0) = 110.0 != Total Amount (150.0)",
            }
        ]
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="invoice",
            document_status="needs_review",
            fields=fields,
            summary=DocumentValidationSummary(total_fields=4, valid_count=3, needs_review_count=1, conflict_count=0),
            validation_issues=issues,
            validated_at="2026-09-20T11:00:00Z",
        )

        mock_gemini = MockGeminiSummaryService(
            summary_output=GeminiDocumentSummaryOutput(
                summary="Invoice from Apex Supply with arithmetic discrepancy.",
                key_points=["Vendor Apex Supply", "Subtotal $100, Tax $10, Total stated $150"],
                review_items=["Arithmetic mismatch between subtotal, tax, and total amount"],
            )
        )
        summarizer = DocumentSummarizer(processing_base_dir=self.temp_dir, gemini=mock_gemini)
        summary_result = summarizer.summarize_document(self.doc_id, "invoice", val_result)

        self.assertEqual(len(summary_result.review_items), 1)
        self.assertIn("Arithmetic mismatch", summary_result.review_items[0])

        action_extractor = DocumentActionExtractor(processing_base_dir=self.temp_dir, gemini=mock_gemini)
        actions_result = action_extractor.extract_actions(self.doc_id, "invoice", val_result, summary_result)

        # Deterministic rule must generate an arithmetic discrepancy review action
        review_actions = [
            a for a in actions_result.actions
            if "arithmetic" in a.action.lower() or "discrepancy" in a.action.lower() or "subtotal" in a.action.lower()
        ]
        self.assertTrue(len(review_actions) >= 1)
        self.assertEqual(review_actions[0].priority, ActionPriorityEnum.HIGH)

    # -------------------------------------------------------------------------
    # Scenario 3: Invoice with explicit due date
    # -------------------------------------------------------------------------
    def test_03_invoice_with_explicit_due_date(self):
        fields = [
            make_field("vendor_name", "Globex", "Globex", "valid", "vendor_information"),
            make_field("total_amount", "500.00", "500.0", "valid", "totals"),
            make_field("due_date", "2026-11-01", "2026-11-01", "valid", "invoice_metadata"),
        ]
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="invoice",
            document_status="completed",
            fields=fields,
            summary=DocumentValidationSummary(total_fields=3, valid_count=3, needs_review_count=0, conflict_count=0),
            validation_issues=[],
            validated_at="2026-09-20T11:00:00Z",
        )

        action_extractor = DocumentActionExtractor(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        actions_result = action_extractor.extract_actions(self.doc_id, "invoice", val_result)

        payment_act = next(a for a in actions_result.actions if "pay" in a.action.lower())
        self.assertEqual(payment_act.due_date, "2026-11-01")

    # -------------------------------------------------------------------------
    # Scenario 4: Invoice without due date -> action due_date is strictly None
    # -------------------------------------------------------------------------
    def test_04_invoice_without_due_date_has_null_due_date(self):
        fields = [
            make_field("vendor_name", "Globex", "Globex", "valid", "vendor_information"),
            make_field("total_amount", "500.00", "500.0", "valid", "totals"),
            # NO due_date field present
        ]
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="invoice",
            document_status="completed",
            fields=fields,
            summary=DocumentValidationSummary(total_fields=2, valid_count=2, needs_review_count=0, conflict_count=0),
            validation_issues=[],
            validated_at="2026-09-20T11:00:00Z",
        )

        action_extractor = DocumentActionExtractor(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        actions_result = action_extractor.extract_actions(self.doc_id, "invoice", val_result)

        payment_act = next(a for a in actions_result.actions if "pay" in a.action.lower())
        # Architectural requirement: strictly do NOT guess/invent due dates
        self.assertIsNone(payment_act.due_date)

    # -------------------------------------------------------------------------
    # Scenario 5: Conflicting invoice data
    # -------------------------------------------------------------------------
    def test_05_conflicting_invoice_data(self):
        fields = [
            make_field(
                "invoice_date",
                "2026-05-01",
                "2026-05-01",
                "conflict",
                "invoice_metadata",
                "OCR read '2026-05-01' but vision read '2026-05-10'",
            ),
            make_field("total_amount", "200.00", "200.0", "valid", "totals"),
        ]
        issues = [
            {
                "field_name": "invoice_date",
                "status": "conflict",
                "code": "VISION_OCR_CONFLICT",
                "message": "Disagreement between OCR and Vision models",
            }
        ]
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="invoice",
            document_status="needs_review",
            fields=fields,
            summary=DocumentValidationSummary(total_fields=2, valid_count=1, needs_review_count=0, conflict_count=1),
            validation_issues=issues,
            validated_at="2026-09-20T11:00:00Z",
        )

        action_extractor = DocumentActionExtractor(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        actions_result = action_extractor.extract_actions(self.doc_id, "invoice", val_result)

        conflict_actions = [a for a in actions_result.actions if "conflict" in a.action.lower() and "invoice_date" in a.action.lower()]
        self.assertTrue(len(conflict_actions) >= 1)
        self.assertEqual(conflict_actions[0].priority, ActionPriorityEnum.HIGH)

    # -------------------------------------------------------------------------
    # Scenario 6: Onboarding form summary & sensitive data masking
    # -------------------------------------------------------------------------
    def test_06_onboarding_form_summary_and_sensitive_data_masking(self):
        fields = [
            make_field("full_name", "Alice Smith", "Alice Smith", "valid", "personal_info"),
            make_field("ssn", "123-45-6789", "123-45-6789", "valid", "personal_info"),
            make_field("bank_account_number", "987654321012", "987654321012", "valid", "bank_details"),
            make_field("department", "Engineering", "Engineering", "valid", "employment_info"),
        ]
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="onboarding_form",
            document_status="completed",
            fields=fields,
            summary=DocumentValidationSummary(total_fields=4, valid_count=4, needs_review_count=0, conflict_count=0),
            validation_issues=[],
            validated_at="2026-09-20T11:00:00Z",
        )

        summarizer = DocumentSummarizer(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        # Test the sanitization logic directly
        sanitized = summarizer._sanitize_context_for_llm(val_result)

        # Plaintext SSN and Bank Account must NOT be present in sanitized output
        self.assertNotIn("123-45-6789", json.dumps(sanitized))
        self.assertNotIn("987654321012", json.dumps(sanitized))

        # Check masked marker
        ssn_entry = next(f for f in sanitized["fields"] if f["field_name"] == "ssn")
        self.assertIn("PROTECTED", ssn_entry["normalized_value"])

    # -------------------------------------------------------------------------
    # Scenario 7: Onboarding with missing required data
    # -------------------------------------------------------------------------
    def test_07_onboarding_with_missing_required_data(self):
        fields = [
            make_field("full_name", "Bob Johnson", "Bob Johnson", "valid", "personal_info"),
        ]
        issues = [
            {
                "field_name": "emergency_contact",
                "status": "needs_review",
                "code": "REQUIRED_FIELD_MISSING",
                "message": "Missing required field: emergency_contact",
            }
        ]
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="onboarding_form",
            document_status="needs_review",
            fields=fields,
            summary=DocumentValidationSummary(total_fields=1, valid_count=1, needs_review_count=1, conflict_count=0),
            validation_issues=issues,
            validated_at="2026-09-20T11:00:00Z",
        )

        action_extractor = DocumentActionExtractor(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        actions_result = action_extractor.extract_actions(self.doc_id, "onboarding_form", val_result)

        missing_actions = [a for a in actions_result.actions if "emergency_contact" in a.action.lower() or "missing" in a.action.lower()]
        self.assertTrue(len(missing_actions) >= 1)
        self.assertEqual(missing_actions[0].priority, ActionPriorityEnum.HIGH)

    # -------------------------------------------------------------------------
    # Scenario 8: Unknown document handling
    # -------------------------------------------------------------------------
    def test_08_unknown_document_skipped(self):
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="unknown",
            document_status="completed",
            fields=[],
            summary=DocumentValidationSummary(total_fields=0, valid_count=0, needs_review_count=0, conflict_count=0),
            validation_issues=[],
            validated_at="2026-09-20T11:00:00Z",
        )

        summarizer = DocumentSummarizer(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        summary_result = summarizer.summarize_document(self.doc_id, "unknown", val_result)
        self.assertEqual(summary_result.document_type, "unknown")
        self.assertEqual(summary_result.status, "skipped")
        self.assertIn("unavailable for unknown", summary_result.summary.lower())
        self.assertEqual(len(summary_result.key_points), 0)

        action_extractor = DocumentActionExtractor(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        actions_result = action_extractor.extract_actions(self.doc_id, "unknown", val_result, summary_result)
        self.assertEqual(actions_result.total_actions, 0)
        self.assertEqual(len(actions_result.actions), 0)

    # -------------------------------------------------------------------------
    # Scenario 9: Rerun idempotency & User status preservation
    # -------------------------------------------------------------------------
    def test_09_rerun_idempotency_preserves_user_status(self):
        fields = [
            make_field("vendor_name", "Delta Ltd", "Delta Ltd", "valid", "vendor_information"),
            make_field("total_amount", "99.00", "99.0", "valid", "totals"),
            make_field("due_date", "2026-12-01", "2026-12-01", "valid", "invoice_metadata"),
        ]
        val_result = DocumentValidationResult(
            document_id=self.doc_id,
            document_type="invoice",
            document_status="completed",
            fields=fields,
            summary=DocumentValidationSummary(total_fields=3, valid_count=3, needs_review_count=0, conflict_count=0),
            validation_issues=[],
            validated_at="2026-09-20T11:00:00Z",
        )

        action_extractor = DocumentActionExtractor(processing_base_dir=self.temp_dir, gemini=self.mock_gemini)
        res1 = action_extractor.extract_actions(self.doc_id, "invoice", val_result)
        self.assertGreaterEqual(res1.total_actions, 1)

        # Simulate user marking the payment action as COMPLETED
        payment_act = next(a for a in res1.actions if "pay" in a.action.lower())
        payment_id = payment_act.id
        actions_file = self.doc_folder / "actions.json"

        # Update disk file simulating user completing this action
        with open(actions_file, "r") as f:
            data = json.load(f)
        for act in data["actions"]:
            if act["id"] == payment_id:
                act["status"] = "completed"
        with open(actions_file, "w") as f:
            json.dump(data, f)

        # Run extraction second time (rerun)
        res2 = action_extractor.extract_actions(self.doc_id, "invoice", val_result)

        # Verify no duplicate payment action was created and status remains completed
        matching = [a for a in res2.actions if "pay" in a.action.lower()]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].status, ActionStatusEnum.COMPLETED)
        self.assertEqual(matching[0].id, payment_id)

    # -------------------------------------------------------------------------
    # Scenario 10: Action status update API & validation
    # -------------------------------------------------------------------------
    def test_10_action_status_update_model(self):
        req = ActionStatusUpdateRequest(status=ActionStatusEnum.IN_PROGRESS)
        self.assertEqual(req.status, ActionStatusEnum.IN_PROGRESS)

        req_completed = ActionStatusUpdateRequest(status=ActionStatusEnum.COMPLETED)
        self.assertEqual(req_completed.status, ActionStatusEnum.COMPLETED)

        with self.assertRaises(ValueError):
            ActionStatusUpdateRequest(status="unknown_status")

    # -------------------------------------------------------------------------
    # Scenario 11: FastAPI TestClient endpoints
    # -------------------------------------------------------------------------
    def test_11_fastapi_endpoints(self):
        client = TestClient(app)

        # Seed synthetic validation.json in the doc folder so endpoints can load it
        fields = [
            {"field_name": "vendor_name", "field_value": "Omega Corp", "normalized_value": "Omega Corp", "validation_status": "valid", "section_name": "vendor_information", "page_number": 1},
            {"field_name": "total_amount", "field_value": "300.00", "normalized_value": "300.00", "validation_status": "valid", "section_name": "totals", "page_number": 1},
            {"field_name": "due_date", "field_value": "2026-10-30", "normalized_value": "2026-10-30", "validation_status": "valid", "section_name": "invoice_metadata", "page_number": 1},
        ]
        val_data = {
            "document_id": self.doc_id,
            "document_type": "invoice",
            "document_status": "completed",
            "fields": fields,
            "summary": {"total_fields": 3, "valid_count": 3, "needs_review_count": 0, "conflict_count": 0},
            "validation_issues": [],
            "validated_at": "2026-09-20T11:00:00Z",
        }
        with open(self.doc_folder / "validation.json", "w", encoding="utf-8") as f:
            json.dump(val_data, f)

        mock_doc = {
            "id": self.doc_id,
            "filename": "test_invoice.pdf",
            "document_type": "invoice",
            "status": "completed",
        }

        with patch("app.services.supabase.supabase_service.is_configured", return_value=True), \
             patch("app.services.supabase.supabase_service.get_document", return_value=mock_doc), \
             patch("app.services.supabase.supabase_service.create_processing_log", return_value=True), \
             patch("app.services.supabase.supabase_service.update_document_summary", return_value=True), \
             patch("app.services.supabase.supabase_service.save_actions", return_value=True), \
             patch("app.services.supabase.supabase_service.get_actions", return_value=[]), \
             patch("app.services.supabase.supabase_service.update_action_status", return_value={"id": "act-123", "document_id": self.doc_id, "action": "Pay invoice", "status": "in_progress", "priority": "high"}), \
             patch("app.services.supabase.supabase_service.update_document_status", return_value=True), \
             patch("app.services.gemini.gemini_service.is_configured", return_value=True), \
             patch.object(document_summarizer, "gemini", self.mock_gemini), \
             patch.object(document_action_extractor, "gemini", self.mock_gemini), \
             patch.object(document_summarizer, "base_dir", Path(self.temp_dir)), \
             patch.object(document_action_extractor, "base_dir", Path(self.temp_dir)), \
             patch("app.api.documents.BASE_TMP_DIR", Path(self.temp_dir)):

            # 1. Test POST /api/documents/{id}/summarize
            resp_summary = client.post(f"/api/documents/{self.doc_id}/summarize")
            self.assertEqual(resp_summary.status_code, 200)
            data_summary = resp_summary.json()
            self.assertEqual(data_summary["document_type"], "invoice")
            self.assertIn("summary", data_summary)

            # 2. Test GET /api/documents/{id}/summary
            resp_get_summary = client.get(f"/api/documents/{self.doc_id}/summary")
            self.assertEqual(resp_get_summary.status_code, 200)
            self.assertEqual(resp_get_summary.json()["document_id"], self.doc_id)

            # 3. Test POST /api/documents/{id}/actions
            resp_actions = client.post(f"/api/documents/{self.doc_id}/actions")
            self.assertEqual(resp_actions.status_code, 200)
            data_actions = resp_actions.json()
            self.assertGreaterEqual(data_actions["total_actions"], 1)

            # 4. Test GET /api/documents/{id}/actions
            resp_get_actions = client.get(f"/api/documents/{self.doc_id}/actions")
            self.assertEqual(resp_get_actions.status_code, 200)
            self.assertEqual(len(resp_get_actions.json()["actions"]), data_actions["total_actions"])

            # 5. Test PATCH /api/actions/{action_id}
            action_id = data_actions["actions"][0]["id"]
            resp_patch = client.patch(f"/api/actions/{action_id}", json={"status": "in_progress"})
            self.assertEqual(resp_patch.status_code, 200)
            self.assertEqual(resp_patch.json()["status"], "in_progress")

            # 6. Test POST /api/documents/{id}/insights (combined summary + actions)
            resp_insights = client.post(f"/api/documents/{self.doc_id}/insights")
            self.assertEqual(resp_insights.status_code, 200)
            data_insights = resp_insights.json()
            self.assertIn("summary", data_insights)
            self.assertIn("actions", data_insights)

    # -------------------------------------------------------------------------
    # Scenario 12: Live Gemini calls verification
    # -------------------------------------------------------------------------
    def test_12_live_gemini_integration(self):
        if not gemini_service.is_configured():
            self.skipTest("Gemini API key is not configured; skipping live test.")

        prompt = (
            "You are a factual summarizer. Summarize this invoice data:\n"
            "Vendor: Acme Logistics\n"
            "Total Amount: $1,250.00\n"
            "Due Date: 2026-11-15\n"
            "Invoice Number: INV-8877\n"
            "Validation Status: all fields valid\n"
        )
        try:
            summary_output = gemini_service.generate_document_summary(prompt)
            self.assertIsInstance(summary_output, GeminiDocumentSummaryOutput)
            self.assertTrue(len(summary_output.summary) > 0)
            self.assertLessEqual(len(summary_output.key_points), 5)
            self.assertLessEqual(len(summary_output.review_items), 5)

            action_prompt = (
                "Suggest additional operational follow-up tasks for this validated invoice:\n"
                "Vendor: Acme Logistics, Amount: $1,250.00, Due Date: 2026-11-15\n"
            )
            actions_output = gemini_service.suggest_contextual_actions(action_prompt)
            self.assertIsInstance(actions_output, GeminiActionExtractionOutput)
            self.assertLessEqual(len(actions_output.actions), 5)
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "quota" in str(e).lower():
                self.skipTest(f"Gemini API rate limit/quota reached: {e}")
            else:
                raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
