import os
import json
import uuid
from typing import List

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.normalizer import (
    FieldNormalizer,
    normalize_date,
    normalize_number,
    normalize_currency,
    normalize_email,
    normalize_phone,
    normalize_text,
)
from app.pipeline.validator import (
    DocumentValidator,
    validate_email,
    validate_phone,
    validate_date_relationship,
    validate_line_item_math,
    validate_invoice_subtotal,
    validate_invoice_tax,
    validate_invoice_total,
)
from app.pipeline.types import (
    ExtractedField,
    DocumentValidationResult,
    ValidationStatusEnum,
)

client = TestClient(app)

print("=" * 60)
print("RUNNING PHASE 9 NORMALIZATION & VALIDATION TEST SUITE")
print("=" * 60)


def test_1_clean_invoice():
    print("\n--- TEST 1: Clean Invoice ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-2026-001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="01/09/2026", section_name="invoice_metadata"),
        ExtractedField(field_name="due_date", field_value="15/09/2026", section_name="invoice_metadata"),
        ExtractedField(field_name="line_item_1_description", field_value="Cloud Hosting", section_name="line_items"),
        ExtractedField(field_name="line_item_1_quantity", field_value=2.0, section_name="line_items"),
        ExtractedField(field_name="line_item_1_unit_price", field_value=100.0, section_name="line_items"),
        ExtractedField(field_name="line_item_1_line_total", field_value=200.0, section_name="line_items"),
        ExtractedField(field_name="subtotal", field_value="₹200.00", section_name="tax_information"),
        ExtractedField(field_name="tax_rate", field_value="18%", section_name="tax_information"),
        ExtractedField(field_name="tax_amount", field_value="36.00", section_name="tax_information"),
        ExtractedField(field_name="discount", field_value="0", section_name="tax_information"),
        ExtractedField(field_name="total", field_value="₹236.00", section_name="tax_information"),
    ]

    validator = DocumentValidator(tolerance=0.05)
    res = validator.normalize_and_validate("doc_test_1", "invoice", fields)

    assert res.document_status == "completed", f"Expected 'completed', got '{res.document_status}'"
    assert res.summary.valid_count == len(fields)
    assert res.summary.needs_review_count == 0
    assert res.summary.conflict_count == 0

    # Verify normalization
    inv_date_f = next(f for f in res.fields if f.field_name == "invoice_date")
    assert inv_date_f.normalized_value == "2026-09-01"
    total_f = next(f for f in res.fields if f.field_name == "total")
    assert total_f.normalized_value == "236" or total_f.normalized_value == "236.00"

    print("[PASS] TEST 1: Clean invoice validated with status='completed'")


def test_2_line_item_mismatch():
    print("\n--- TEST 2: Line Item Mismatch (2 * 100 != 250) ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="2026-09-01", section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value="250", section_name="tax_information"),
        ExtractedField(field_name="line_item_1_quantity", field_value=2.0, section_name="line_items"),
        ExtractedField(field_name="line_item_1_unit_price", field_value=100.0, section_name="line_items"),
        ExtractedField(field_name="line_item_1_line_total", field_value=250.0, section_name="line_items"),
    ]

    validator = DocumentValidator(tolerance=0.05)
    res = validator.normalize_and_validate("doc_test_2", "invoice", fields)

    assert res.document_status == "needs_review", f"Expected 'needs_review', got '{res.document_status}'"
    tot_f = next(f for f in res.fields if f.field_name == "line_item_1_line_total")
    assert tot_f.validation_status == ValidationStatusEnum.NEEDS_REVIEW.value
    assert "Line item total does not match quantity × unit price" in tot_f.validation_message

    print("[PASS] TEST 2: Line item mismatch flagged with needs_review and explicit reason")


def test_3_subtotal_mismatch():
    print("\n--- TEST 3: Subtotal Mismatch (100 + 200 + 300 = 600 != 700) ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="2026-09-01", section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value="700", section_name="tax_information"),
        ExtractedField(field_name="line_item_1_line_total", field_value=100.0, section_name="line_items"),
        ExtractedField(field_name="line_item_2_line_total", field_value=200.0, section_name="line_items"),
        ExtractedField(field_name="line_item_3_line_total", field_value=300.0, section_name="line_items"),
        ExtractedField(field_name="subtotal", field_value="700.00", section_name="tax_information"),
    ]

    validator = DocumentValidator(tolerance=0.05)
    res = validator.normalize_and_validate("doc_test_3", "invoice", fields)

    assert res.document_status == "needs_review"
    sub_f = next(f for f in res.fields if f.field_name == "subtotal")
    assert sub_f.validation_status == ValidationStatusEnum.NEEDS_REVIEW.value
    assert "Invoice subtotal does not match the sum of line items" in sub_f.validation_message

    print("[PASS] TEST 3: Subtotal mismatch flagged with needs_review")


def test_4_total_mismatch():
    print("\n--- TEST 4: Total Mismatch (1000 + 180 - 0 = 1180 != 1500) ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="2026-09-01", section_name="invoice_metadata"),
        ExtractedField(field_name="subtotal", field_value="1000.00", section_name="tax_information"),
        ExtractedField(field_name="tax_amount", field_value="180.00", section_name="tax_information"),
        ExtractedField(field_name="discount", field_value="0.00", section_name="tax_information"),
        ExtractedField(field_name="total", field_value="1500.00", section_name="tax_information"),
    ]

    validator = DocumentValidator(tolerance=0.05)
    res = validator.normalize_and_validate("doc_test_4", "invoice", fields)

    assert res.document_status == "needs_review"
    tot_f = next(f for f in res.fields if f.field_name == "total")
    assert tot_f.validation_status == ValidationStatusEnum.NEEDS_REVIEW.value
    assert "Invoice total does not match subtotal + tax - discount" in tot_f.validation_message

    print("[PASS] TEST 4: Total mismatch flagged with needs_review")


def test_5_invalid_email():
    print("\n--- TEST 5: Invalid Email ('durvankur@') ---")
    fields = [
        ExtractedField(field_name="full_name", field_value="Durvankur Joshi", section_name="personal_information"),
        ExtractedField(field_name="email", field_value="durvankur@", section_name="contact_information"),
    ]

    validator = DocumentValidator()
    res = validator.normalize_and_validate("doc_test_5", "onboarding_form", fields)

    assert res.document_status == "needs_review"
    email_f = next(f for f in res.fields if f.field_name == "email")
    assert email_f.validation_status == ValidationStatusEnum.NEEDS_REVIEW.value
    assert "Email format is invalid" in email_f.validation_message

    print("[PASS] TEST 5: Malformed email correctly flagged as needs_review")


def test_6_date_relationship():
    print("\n--- TEST 6: Date Relationship (due_date < invoice_date) ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="2026-09-20", section_name="invoice_metadata"),
        ExtractedField(field_name="due_date", field_value="2026-09-10", section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value="100.00", section_name="tax_information"),
    ]

    validator = DocumentValidator()
    res = validator.normalize_and_validate("doc_test_6", "invoice", fields)

    assert res.document_status == "needs_review"
    due_f = next(f for f in res.fields if f.field_name == "due_date")
    assert due_f.validation_status == ValidationStatusEnum.NEEDS_REVIEW.value
    assert "Due date is earlier than invoice date" in due_f.validation_message

    print("[PASS] TEST 6: Due date preceding invoice date correctly flagged")


def test_7_missing_optional_field():
    print("\n--- TEST 7: Missing Optional Field ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="2026-09-01", section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value="100.00", section_name="tax_information"),
        ExtractedField(field_name="notes", field_value=None, section_name="notes"),
        ExtractedField(field_name="purchase_order_number", field_value=None, section_name="invoice_metadata"),
    ]

    validator = DocumentValidator()
    res = validator.normalize_and_validate("doc_test_7", "invoice", fields)

    assert res.document_status == "completed"
    notes_f = next(f for f in res.fields if f.field_name == "notes")
    assert notes_f.validation_status == ValidationStatusEnum.VALID.value

    print("[PASS] TEST 7: Missing optional field does NOT fail validation")


def test_8_missing_required_field():
    print("\n--- TEST 8: Missing Required Field (invoice_number absent) ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_date", field_value="2026-09-01", section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value="100.00", section_name="tax_information"),
    ]

    validator = DocumentValidator()
    res = validator.normalize_and_validate("doc_test_8", "invoice", fields)

    assert res.document_status == "needs_review"
    inv_num_f = next((f for f in res.fields if f.field_name == "invoice_number"), None)
    assert inv_num_f is not None
    assert inv_num_f.validation_status == ValidationStatusEnum.NEEDS_REVIEW.value
    assert "Required invoice field 'invoice_number' is missing" in inv_num_f.validation_message

    print("[PASS] TEST 8: Missing required invoice_number caught with needs_review")


def test_9_conflict_detection():
    print("\n--- TEST 9: Conflict Detection (INV-1001 vs INV-1002) ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-1001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_number", field_value="INV-1002", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="2026-09-01", section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value="100.00", section_name="tax_information"),
    ]

    validator = DocumentValidator()
    res = validator.normalize_and_validate("doc_test_9", "invoice", fields)

    assert res.document_status == "needs_review"
    inv_fields = [f for f in res.fields if f.field_name == "invoice_number"]
    assert len(inv_fields) == 2
    for f in inv_fields:
        assert f.validation_status == ValidationStatusEnum.CONFLICT.value
        assert "Multiple conflicting values detected" in f.validation_message

    print("[PASS] TEST 9: Conflicting values flagged with status='conflict'")


def test_10_identical_duplicates():
    print("\n--- TEST 10: Identical Duplicates (INV-1001 vs INV-1001) ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-1001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_number", field_value="INV-1001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="2026-09-01", section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value="100.00", section_name="tax_information"),
    ]

    validator = DocumentValidator()
    res = validator.normalize_and_validate("doc_test_10", "invoice", fields)

    inv_fields = [f for f in res.fields if f.field_name == "invoice_number"]
    assert len(inv_fields) == 2
    for f in inv_fields:
        assert f.validation_status == ValidationStatusEnum.VALID.value

    print("[PASS] TEST 10: Identical duplicate values are NOT treated as conflicts")


def test_11_onboarding_validation():
    print("\n--- TEST 11: Onboarding Validation ---")
    fields = [
        ExtractedField(field_name="full_name", field_value="Jane Doe", section_name="personal_information"),
        ExtractedField(field_name="date_of_birth", field_value="15/08/1995", section_name="personal_information"),
        ExtractedField(field_name="email", field_value="  JANE.DOE@EXAMPLE.COM  ", section_name="contact_information"),
        ExtractedField(field_name="phone", field_value="+1 (555) 234-5678", section_name="contact_information"),
        ExtractedField(field_name="employee_id", field_value="EMP-9021", section_name="employment_information"),
        ExtractedField(field_name="joining_date", field_value="01-Sep-2026", section_name="employment_information"),
    ]

    validator = DocumentValidator()
    res = validator.normalize_and_validate("doc_test_11", "onboarding_form", fields)

    assert res.document_status == "completed"
    assert res.summary.valid_count == len(fields)

    email_f = next(f for f in res.fields if f.field_name == "email")
    assert email_f.normalized_value == "jane.doe@example.com"
    dob_f = next(f for f in res.fields if f.field_name == "date_of_birth")
    assert dob_f.normalized_value == "1995-08-15"
    phone_f = next(f for f in res.fields if f.field_name == "phone")
    assert phone_f.normalized_value == "+15552345678"

    print("[PASS] TEST 11: Valid onboarding form normalized & validated with status='completed'")


def test_12_rerun_idempotency():
    print("\n--- TEST 12: Rerun Idempotency ---")
    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-2026-001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value="01/09/2026", section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value="200.00", section_name="tax_information"),
    ]

    validator = DocumentValidator()
    res1 = validator.normalize_and_validate("doc_rerun", "invoice", fields)
    res2 = validator.normalize_and_validate("doc_rerun", "invoice", res1.fields)

    assert res1.document_status == res2.document_status == "completed"
    assert len(res1.fields) == len(res2.fields)
    assert res1.summary.valid_count == res2.summary.valid_count

    print("[PASS] TEST 12: Validation rerun produces identical idempotent results")


def test_13_anti_corruption_preservation():
    print("\n--- TEST 13: Mandatory Anti-Corruption Test ---")
    original_val = "01/09/2026"
    currency_val = "₹ 1,25,000.50"
    email_val = "  DURVANKUR@EXAMPLE.COM  "
    phone_val = "+91 98765 43210"

    fields = [
        ExtractedField(field_name="vendor_name", field_value="Acme Corp", section_name="vendor_information"),
        ExtractedField(field_name="invoice_number", field_value="INV-001", section_name="invoice_metadata"),
        ExtractedField(field_name="invoice_date", field_value=original_val, section_name="invoice_metadata"),
        ExtractedField(field_name="total", field_value=currency_val, section_name="tax_information"),
        ExtractedField(field_name="vendor_email", field_value=email_val, section_name="vendor_information"),
        ExtractedField(field_name="vendor_phone", field_value=phone_val, section_name="vendor_information"),
    ]

    validator = DocumentValidator()
    res = validator.normalize_and_validate("doc_corrupt_test", "invoice", fields)

    inv_date_f = next(f for f in res.fields if f.field_name == "invoice_date")
    total_f = next(f for f in res.fields if f.field_name == "total")
    email_f = next(f for f in res.fields if f.field_name == "vendor_email")
    phone_f = next(f for f in res.fields if f.field_name == "vendor_phone")

    # Anti-corruption verification: original field_value MUST NOT be altered
    assert inv_date_f.field_value == original_val, f"Expected '{original_val}', got '{inv_date_f.field_value}'"
    assert inv_date_f.normalized_value == "2026-09-01"

    assert total_f.field_value == currency_val
    assert total_f.normalized_value == "125000.5" or total_f.normalized_value == "125000.50"

    assert email_f.field_value == email_val
    assert email_f.normalized_value == "durvankur@example.com"

    assert phone_f.field_value == phone_val
    assert phone_f.normalized_value == "+919876543210"

    print("[PASS] TEST 13: Mandatory Anti-Corruption: original field_values remain strictly unaltered!")


def test_14_fastapi_endpoints():
    print("\n--- TEST 14: FastAPI Endpoints ---")
    from unittest.mock import patch

    doc_id = str(uuid.uuid4())
    target_dir = os.path.join("tmp", "processing", doc_id)
    os.makedirs(target_dir, exist_ok=True)

    mock_doc = {
        "id": doc_id,
        "filename": "test_invoice.pdf",
        "mime_type": "application/pdf",
        "status": "extracted",
        "document_type": "invoice",
    }

    extraction_artifact = {
        "document_id": doc_id,
        "document_type": "invoice",
        "status": "extracted",
        "fields": [
            {
                "field_name": "vendor_name",
                "field_value": "Apex Innovations",
                "section_name": "vendor_information",
                "confidence": 0.95,
            },
            {
                "field_name": "invoice_number",
                "field_value": "INV-7788",
                "section_name": "invoice_metadata",
                "confidence": 0.98,
            },
            {
                "field_name": "invoice_date",
                "field_value": "15 Sep 2026",
                "section_name": "invoice_metadata",
                "confidence": 0.99,
            },
            {
                "field_name": "total",
                "field_value": "$500.00",
                "section_name": "tax_information",
                "confidence": 0.95,
            },
        ],
        "section_data": {},
        "extracted_at": "2026-09-20T00:00:00Z",
        "metadata": {},
    }

    with open(os.path.join(target_dir, "extraction.json"), "w", encoding="utf-8") as f:
        json.dump(extraction_artifact, f)

    with patch("app.api.documents.supabase_service.is_configured", return_value=True), \
         patch("app.api.documents.supabase_service.get_document", return_value=mock_doc), \
         patch("app.api.documents.supabase_service.update_document_status", return_value=mock_doc), \
         patch("app.api.documents.supabase_service.create_processing_log", return_value={}), \
         patch("app.api.documents.supabase_service.save_validated_fields", return_value=[]):

        # Call POST /api/documents/{id}/validate
        post_res = client.post(f"/api/documents/{doc_id}/validate")
        assert post_res.status_code == 200, f"Expected 200, got {post_res.status_code}: {post_res.text}"
        val_data = post_res.json()

        assert val_data["document_id"] == doc_id
        assert val_data["document_status"] == "completed"
        assert val_data["summary"]["valid_count"] == 4
        assert val_data["summary"]["needs_review_count"] == 0

        # Call GET /api/documents/{id}/validation
        get_res = client.get(f"/api/documents/{doc_id}/validation")
        assert get_res.status_code == 200
        assert get_res.json()["document_status"] == "completed"

    # Also test precondition failures
    doc_unextracted = str(uuid.uuid4())
    mock_unextracted_doc = {
        "id": doc_unextracted,
        "filename": "unextracted.pdf",
        "status": "classified",
    }
    with patch("app.api.documents.supabase_service.is_configured", return_value=True), \
         patch("app.api.documents.supabase_service.get_document", return_value=mock_unextracted_doc):
        bad_res = client.post(f"/api/documents/{doc_unextracted}/validate")
        assert bad_res.status_code == 400
        assert "section detection" in bad_res.json()["detail"].lower()

    print("[PASS] TEST 14: FastAPI POST /validate and GET /validation verified successfully")


if __name__ == "__main__":
    test_1_clean_invoice()
    test_2_line_item_mismatch()
    test_3_subtotal_mismatch()
    test_4_total_mismatch()
    test_5_invalid_email()
    test_6_date_relationship()
    test_7_missing_optional_field()
    test_8_missing_required_field()
    test_9_conflict_detection()
    test_10_identical_duplicates()
    test_11_onboarding_validation()
    test_12_rerun_idempotency()
    test_13_anti_corruption_preservation()
    test_14_fastapi_endpoints()

    print("\n" + "=" * 60)
    print("ALL 14 PHASE 9 VALIDATION & NORMALIZATION TESTS PASSED!")
    print("=" * 60)
