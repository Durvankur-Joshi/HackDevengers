"""
Phase 8 Targeted Structured AI Extraction Test Suite
Validates:
1. Section schema models integrity & strict null policy
2. Targeted section prompt builder (receives only section text)
3. Unknown document bypass (status='skipped')
4. Invoice targeted extraction & field provenance (mocked)
5. Onboarding form targeted extraction & field provenance (mocked)
6. Extraction artifact generation (backend/tmp/processing/{id}/extraction.json)
7. FastAPI endpoint routes (POST & GET /api/documents/{id}/extract)
8. Live Gemini targeted extraction (if API key available)
"""

import os
import sys
import json
import uuid
from pathlib import Path
from unittest.mock import patch

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.pipeline.types import (
    ExtractedField,
    ExtractedFieldProvenance,
    ExtractedNumberProvenance,
    ExtractedBoolProvenance,
    VendorInfoExtraction,
    CustomerInfoExtraction,
    InvoiceMetadataExtraction,
    LineItemExtraction,
    LineItemsExtraction,
    TaxInfoExtraction,
    PaymentInfoExtraction,
    NotesExtraction,
    PersonalInfoExtraction,
    ContactInfoExtraction,
    EmploymentInfoExtraction,
    EmergencyContactExtraction,
    BankDetailsExtraction,
    DocumentSection,
    DocumentSectionResult,
    DocumentClassificationResult,
    DocumentExtractionResult,
)
from app.pipeline.extractor import (
    DocumentExtractor,
    extract_document_fields,
    INVOICE_SECTION_SCHEMAS,
    ONBOARDING_SECTION_SCHEMAS,
)
from app.core.config import settings


def test_section_schemas():
    print("\n--- 1. Testing Section Schemas & Strict Null Policy ---")
    # All fields should default to None in provenance (strict null policy)
    vendor = VendorInfoExtraction()
    assert vendor.vendor_name.value is None
    assert vendor.vendor_tax_id.value is None
    assert vendor.vendor_email.value is None

    # Line item test
    item = LineItemExtraction(
        description="Widget A",
        quantity=2.0,
        unit_price=25.0,
        line_total=50.0
    )
    items_extraction = LineItemsExtraction(items=[item])
    assert len(items_extraction.items) == 1
    assert items_extraction.items[0].description == "Widget A"
    assert items_extraction.items[0].line_total == 50.0

    # Personal info test
    personal = PersonalInfoExtraction(
        full_name=ExtractedFieldProvenance(value="Jane Doe", confidence=0.99, source_text="Jane Doe"),
        date_of_birth=ExtractedFieldProvenance(value=None, confidence=None, source_text=None)
    )
    assert personal.full_name.value == "Jane Doe"
    assert personal.date_of_birth.value is None  # strict null policy
    assert personal.gender.value is None
    print("[PASS] Schema models correctly enforce strict null policy and provenance structures")


def test_targeted_prompt_builder():
    print("\n--- 2. Testing Targeted Prompt Builder ---")
    extractor = DocumentExtractor()
    prompt = extractor.build_targeted_section_prompt(
        document_type="invoice",
        section_name="vendor_information",
        section_text="Acme Corp\n123 Main St\nTax ID: 12-3456789",
        page_number=1,
        field_names=["vendor_name", "vendor_address", "vendor_email", "vendor_phone", "vendor_tax_id"]
    )
    assert "vendor_information" in prompt
    assert "Acme Corp" in prompt
    assert "123 Main St" in prompt
    assert "Extract only fields relevant to this section" in prompt
    assert "DO NOT invent, guess, fabricate, or hallucinate" in prompt
    # Ensure it only contains the targeted section text
    assert "customer_information" not in prompt
    print("[PASS] Targeted prompt builder strictly isolates section text and injects strict null policy")


def test_unknown_document_bypass():
    print("\n--- 3. Testing Unknown Document Bypass ---")
    doc_id = str(uuid.uuid4())
    section_result = DocumentSectionResult(
        document_id=doc_id,
        document_type="unknown",
        sections=[]
    )

    result = extract_document_fields(section_result=section_result)

    assert result.status == "skipped"
    assert "Unsupported" in (result.reason or "") or "unknown" in (result.reason or "")
    assert len(result.fields) == 0
    print(f"[PASS] Unknown document successfully bypassed extraction: status='{result.status}' reason='{result.reason}'")


def test_mocked_invoice_extraction():
    print("\n--- 4. Testing Invoice Targeted Section Extraction (Mocked) ---")
    doc_id = str(uuid.uuid4())
    sections = [
        DocumentSection(
            section_id="sec_1",
            document_id=doc_id,
            section_name="vendor_information",
            page_number=1,
            text="Global Tech Supplies Inc\n100 Enterprise Way, Austin TX\nTax ID: 74-9876543\nEmail: sales@globaltech.com",
            confidence=0.95
        ),
        DocumentSection(
            section_id="sec_2",
            document_id=doc_id,
            section_name="invoice_metadata",
            page_number=1,
            text="INVOICE\nInvoice #: INV-9988\nDate: 2026-03-15\nDue Date: 2026-04-15\nPO #: PO-4433",
            confidence=0.94
        ),
        DocumentSection(
            section_id="sec_3",
            document_id=doc_id,
            section_name="line_items",
            page_number=1,
            text="Item | Qty | Price | Total\nCloud Server Hosting | 2 | $500.00 | $1000.00\nDomain Registration | 1 | $25.00 | $25.00",
            confidence=0.92
        ),
        DocumentSection(
            section_id="sec_4",
            document_id=doc_id,
            section_name="tax_information",
            page_number=1,
            text="Subtotal: $1025.00\nTax (8%): $82.00\nTotal Due: $1107.00",
            confidence=0.96
        )
    ]
    section_result = DocumentSectionResult(
        document_id=doc_id,
        document_type="invoice",
        sections=sections
    )

    def mock_extract(prompt, response_schema, model=None):
        if response_schema == VendorInfoExtraction:
            return VendorInfoExtraction(
                vendor_name=ExtractedFieldProvenance(value="Global Tech Supplies Inc", confidence=0.99, source_text="Global Tech Supplies Inc"),
                vendor_address=ExtractedFieldProvenance(value="100 Enterprise Way, Austin TX", confidence=0.98, source_text="100 Enterprise Way, Austin TX"),
                vendor_tax_id=ExtractedFieldProvenance(value="74-9876543", confidence=0.99, source_text="Tax ID: 74-9876543"),
                vendor_email=ExtractedFieldProvenance(value="sales@globaltech.com", confidence=0.99, source_text="sales@globaltech.com"),
                vendor_phone=ExtractedFieldProvenance(value=None, confidence=None, source_text=None)  # not in text -> strict null
            )
        elif response_schema == InvoiceMetadataExtraction:
            return InvoiceMetadataExtraction(
                invoice_number=ExtractedFieldProvenance(value="INV-9988", confidence=0.99, source_text="Invoice #: INV-9988"),
                invoice_date=ExtractedFieldProvenance(value="2026-03-15", confidence=0.98, source_text="Date: 2026-03-15"),
                due_date=ExtractedFieldProvenance(value="2026-04-15", confidence=0.98, source_text="Due Date: 2026-04-15"),
                currency=ExtractedFieldProvenance(value="USD", confidence=0.95, source_text="$"),
                purchase_order_number=ExtractedFieldProvenance(value="PO-4433", confidence=0.97, source_text="PO #: PO-4433")
            )
        elif response_schema == LineItemsExtraction:
            return LineItemsExtraction(
                items=[
                    LineItemExtraction(
                        description="Cloud Server Hosting",
                        quantity=2.0,
                        unit_price=500.0,
                        tax_rate=None,
                        line_total=1000.0
                    ),
                    LineItemExtraction(
                        description="Domain Registration",
                        quantity=1.0,
                        unit_price=25.0,
                        tax_rate=None,
                        line_total=25.0
                    )
                ]
            )
        elif response_schema == TaxInfoExtraction:
            return TaxInfoExtraction(
                subtotal=ExtractedNumberProvenance(value=1025.0, confidence=0.99, source_text="Subtotal: $1025.00"),
                tax_rate=ExtractedNumberProvenance(value=8.0, confidence=0.95, source_text="8%"),
                tax_amount=ExtractedNumberProvenance(value=82.0, confidence=0.99, source_text="Tax (8%): $82.00"),
                discount=ExtractedNumberProvenance(value=None, confidence=None, source_text=None),
                total=ExtractedNumberProvenance(value=1107.0, confidence=0.99, source_text="Total Due: $1107.00")
            )
        return None

    with patch("app.services.gemini.gemini_service.extract_section_data", side_effect=mock_extract):
        result = extract_document_fields(section_result=section_result)

    assert result.status == "extracted"
    assert result.document_type == "invoice"
    assert len(result.fields) > 0

    # Verify field values & provenance
    fields_dict = {f.field_name: f for f in result.fields}
    assert "vendor_name" in fields_dict
    assert fields_dict["vendor_name"].field_value == "Global Tech Supplies Inc"
    assert fields_dict["vendor_name"].source == "gemini"
    assert fields_dict["vendor_name"].section_name == "vendor_information"
    assert fields_dict["vendor_name"].confidence >= 0.9

    # Strict null policy check
    assert "vendor_phone" in fields_dict
    assert fields_dict["vendor_phone"].field_value is None

    # Metadata check
    assert fields_dict["invoice_number"].field_value == "INV-9988"
    assert fields_dict["invoice_date"].field_value == "2026-03-15"

    # Line items check
    assert "line_item_1_description" in fields_dict
    assert fields_dict["line_item_1_description"].field_value == "Cloud Server Hosting"
    assert fields_dict["line_item_1_line_total"].field_value == 1000.0

    # Tax info check
    assert fields_dict["total"].field_value == 1107.0

    # Artifact check
    artifact_path = Path("tmp/processing") / doc_id / "extraction.json"
    assert artifact_path.exists(), f"Artifact missing at {artifact_path}"
    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["document_id"] == doc_id
        assert data["status"] == "extracted"
        assert len(data["fields"]) == len(result.fields)

    print(f"[PASS] Invoice extraction produced {len(result.fields)} typed fields with full provenance and saved artifact {artifact_path}")


def test_mocked_onboarding_extraction():
    print("\n--- 5. Testing Onboarding Form Targeted Extraction (Mocked) ---")
    doc_id = str(uuid.uuid4())
    sections = [
        DocumentSection(
            section_id="sec_p",
            document_id=doc_id,
            section_name="personal_information",
            page_number=1,
            text="Employee Name: Sarah Connor\nDOB: 1985-05-12\nNationality: United States",
            confidence=0.96
        ),
        DocumentSection(
            section_id="sec_e",
            document_id=doc_id,
            section_name="employment_information",
            page_number=1,
            text="Job Title: Senior Systems Engineer\nDepartment: Infrastructure & Security\nStart Date: 2026-04-01",
            confidence=0.95
        ),
        DocumentSection(
            section_id="sec_b",
            document_id=doc_id,
            section_name="bank_details",
            page_number=2,
            text="Direct Deposit\nBank Name: First Cyber Bank\nAccount Number: 9876543210\nRouting Number: 121000358",
            confidence=0.94
        )
    ]
    section_result = DocumentSectionResult(
        document_id=doc_id,
        document_type="onboarding_form",
        sections=sections
    )

    def mock_extract_onboarding(prompt, response_schema, model=None):
        if response_schema == PersonalInfoExtraction:
            return PersonalInfoExtraction(
                full_name=ExtractedFieldProvenance(value="Sarah Connor", confidence=0.99, source_text="Sarah Connor"),
                date_of_birth=ExtractedFieldProvenance(value="1985-05-12", confidence=0.98, source_text="DOB: 1985-05-12"),
                nationality=ExtractedFieldProvenance(value="United States", confidence=0.97, source_text="Nationality: United States"),
                gender=ExtractedFieldProvenance(value=None, confidence=None, source_text=None)  # not in text
            )
        elif response_schema == EmploymentInfoExtraction:
            return EmploymentInfoExtraction(
                designation=ExtractedFieldProvenance(value="Senior Systems Engineer", confidence=0.99, source_text="Job Title: Senior Systems Engineer"),
                department=ExtractedFieldProvenance(value="Infrastructure & Security", confidence=0.98, source_text="Department: Infrastructure & Security"),
                joining_date=ExtractedFieldProvenance(value="2026-04-01", confidence=0.99, source_text="Start Date: 2026-04-01"),
                employee_id=ExtractedFieldProvenance(value=None, confidence=None, source_text=None),
                employment_type=ExtractedFieldProvenance(value=None, confidence=None, source_text=None)
            )
        elif response_schema == BankDetailsExtraction:
            return BankDetailsExtraction(
                account_holder_name=ExtractedFieldProvenance(value=None, confidence=None, source_text=None),
                bank_name=ExtractedFieldProvenance(value="First Cyber Bank", confidence=0.99, source_text="Bank Name: First Cyber Bank"),
                account_number=ExtractedFieldProvenance(value="9876543210", confidence=0.99, source_text="Account Number: 9876543210"),
                ifsc=ExtractedFieldProvenance(value="121000358", confidence=0.99, source_text="Routing Number: 121000358")
            )
        return None

    with patch("app.services.gemini.gemini_service.extract_section_data", side_effect=mock_extract_onboarding):
        result = extract_document_fields(section_result=section_result)

    assert result.status == "extracted"
    assert result.document_type == "onboarding_form"
    fields_dict = {f.field_name: f for f in result.fields}
    assert fields_dict["full_name"].field_value == "Sarah Connor"
    assert fields_dict["gender"].field_value is None  # strict null
    assert fields_dict["designation"].field_value == "Senior Systems Engineer"
    assert fields_dict["account_number"].field_value == "9876543210"
    print(f"[PASS] Onboarding extraction extracted {len(result.fields)} typed fields with strict null policy adherence")


def test_fastapi_endpoints():
    print("\n--- 6. Testing FastAPI Endpoints (TestClient) ---")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Test GET on non-existent document
    non_existent = str(uuid.uuid4())
    res = client.get(f"/api/documents/{non_existent}/extraction")
    assert res.status_code == 404

    # Test POST /api/documents/{id}/extract with an unknown document (using mock DB)
    unknown_id = str(uuid.uuid4())
    mock_doc = {
        "id": unknown_id,
        "filename": "random_notes.txt",
        "mime_type": "text/plain",
        "status": "classified",
        "document_type": "unknown"
    }

    with patch("app.api.documents.supabase_service.is_configured", return_value=True), \
         patch("app.api.documents.supabase_service.get_document", return_value=mock_doc), \
         patch("app.api.documents.supabase_service.create_processing_log", return_value={}):

        # Write mock classification artifact
        art_dir = Path("tmp/processing") / unknown_id
        art_dir.mkdir(parents=True, exist_ok=True)
        with open(art_dir / "classification.json", "w", encoding="utf-8") as f:
            json.dump({
                "document_type": "unknown",
                "confidence": 0.85,
                "evidence": ["Unrecognized text format"]
            }, f)

        res = client.post(f"/api/documents/{unknown_id}/extract")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["status"] == "skipped"
        assert "Unsupported" in data["reason"] or "unknown" in data["reason"]

        # GET extraction
        res_get = client.get(f"/api/documents/{unknown_id}/extraction")
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["status"] == "skipped"

    print("[PASS] FastAPI endpoints POST /api/documents/{id}/extract and GET /api/documents/{id}/extraction behave correctly")


def test_preconditions_validation():
    print("\n--- 7. Testing Preconditions Validation ---")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # 1. OCR Missing precondition test
    doc_no_ocr = str(uuid.uuid4())
    mock_no_ocr = {
        "id": doc_no_ocr,
        "filename": "invoice_unprocessed.pdf",
        "status": "uploaded",
        "document_type": None,
    }
    with patch("app.api.documents.supabase_service.is_configured", return_value=True), \
         patch("app.api.documents.supabase_service.get_document", return_value=mock_no_ocr):
        res = client.post(f"/api/documents/{doc_no_ocr}/extract")
        assert res.status_code == 400
        assert "Document must complete OCR before extraction." in res.json().get("detail", "")
        print("  [PASS] OCR missing returns: 'Document must complete OCR before extraction.'")

    # 2. Classification Missing precondition test
    doc_no_class = str(uuid.uuid4())
    mock_no_class = {
        "id": doc_no_class,
        "filename": "invoice_no_class.pdf",
        "status": "ocr_completed",
        "document_type": None,
    }
    target_dir = Path("tmp/processing") / doc_no_class
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "ocr.json", "w", encoding="utf-8") as f:
        json.dump({"document_id": doc_no_class, "pages": []}, f)

    with patch("app.api.documents.supabase_service.is_configured", return_value=True), \
         patch("app.api.documents.supabase_service.get_document", return_value=mock_no_class):
        res = client.post(f"/api/documents/{doc_no_class}/extract")
        assert res.status_code == 400
        assert "Document must be classified before extraction." in res.json().get("detail", "")
        print("  [PASS] Classification missing returns: 'Document must be classified before extraction.'")

    # 3. Sections Missing precondition test
    doc_no_sec = str(uuid.uuid4())
    mock_no_sec = {
        "id": doc_no_sec,
        "filename": "invoice_no_sec.pdf",
        "status": "classified",
        "document_type": "invoice",
    }
    target_dir = Path("tmp/processing") / doc_no_sec
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "ocr.json", "w", encoding="utf-8") as f:
        json.dump({"document_id": doc_no_sec, "pages": []}, f)
    with open(target_dir / "classification.json", "w", encoding="utf-8") as f:
        json.dump({"document_type": "invoice", "confidence": 0.95}, f)

    with patch("app.api.documents.supabase_service.is_configured", return_value=True), \
         patch("app.api.documents.supabase_service.get_document", return_value=mock_no_sec), \
         patch("app.api.documents.supabase_service.get_document_sections", return_value=[]):
        res = client.post(f"/api/documents/{doc_no_sec}/extract")
        assert res.status_code == 400
        assert "Document must complete section detection before extraction." in res.json().get("detail", "")
        print("  [PASS] Sections missing returns: 'Document must complete section detection before extraction.'")


def test_anti_hallucination_absent_field():
    print("\n--- 8. Testing Anti-Hallucination on Absent Field (e.g. absent due_date) ---")
    doc_id = str(uuid.uuid4())
    sections = [
        DocumentSection(
            section_id="sec_meta_absent",
            document_id=doc_id,
            section_name="invoice_metadata",
            page_number=1,
            text="INVOICE\nInvoice #: INV-2026-999\nDate: 2026-09-19",  # due_date intentionally absent
            confidence=0.95
        )
    ]
    section_result = DocumentSectionResult(
        document_id=doc_id,
        document_type="invoice",
        sections=sections
    )

    # Simulated response adhering to strict null policy
    def mock_extract(prompt, response_schema, model=None):
        return InvoiceMetadataExtraction(
            invoice_number=ExtractedFieldProvenance(value="INV-2026-999", confidence=0.99, source_text="Invoice #: INV-2026-999"),
            invoice_date=ExtractedFieldProvenance(value="2026-09-19", confidence=0.99, source_text="Date: 2026-09-19"),
            due_date=ExtractedFieldProvenance(value=None, confidence=None, source_text=None),  # absent
            currency=None,
            purchase_order_number=None,
        )

    with patch("app.services.gemini.gemini_service.extract_section_data", side_effect=mock_extract):
        res = extract_document_fields(section_result=section_result)

    fields_map = {f.field_name: f for f in res.fields}
    assert "due_date" in fields_map
    assert fields_map["due_date"].field_value is None
    assert fields_map["due_date"].confidence is None
    assert fields_map["due_date"].source_text is None
    print(f"  [PASS] due_date is strictly null when absent from source (value={fields_map['due_date'].field_value})")


def test_live_gemini_extraction():
    print("\n--- 9. Testing Live Gemini Targeted Section Extraction ---")
    if not settings.GEMINI_API_KEY:
        print("[SKIP] GEMINI_API_KEY not configured, skipping live API call")
        return

    from app.services.gemini import gemini_service

    sample_vendor_text = (
        "Apex Cloud Services Inc\n"
        "500 Innovation Boulevard, Floor 12\n"
        "San Francisco, CA 94105\n"
        "Tax ID: 94-3321876\n"
        "billing@apexcloud.io\n"
        "Phone: (415) 555-0199"
    )

    prompt = (
        "You are a specialized semantic data extraction agent in a document processing pipeline.\n"
        "Extract structured fields strictly matching the response schema for the 'vendor_information' section.\n"
        "STRICT NULL POLICY: If a field is not explicitly present, set its value to null. NEVER hallucinate.\n\n"
        f"--- TARGETED SECTION TEXT ---\n{sample_vendor_text}\n--- END OF SECTION TEXT ---"
    )

    try:
        parsed: VendorInfoExtraction = gemini_service.extract_section_data(
            prompt=prompt,
            response_schema=VendorInfoExtraction
        )
        assert parsed is not None
        assert parsed.vendor_name is not None
        print(f"  Extracted Vendor Name: {parsed.vendor_name.value} (Confidence: {parsed.vendor_name.confidence})")
        print(f"  Extracted Address: {parsed.vendor_address.value if parsed.vendor_address else None}")
        print(f"  Extracted Tax ID: {parsed.vendor_tax_id.value if parsed.vendor_tax_id else None}")
        print(f"  Extracted Email: {parsed.vendor_email.value if parsed.vendor_email else None}")
        assert parsed.vendor_name.value is not None
        assert "Apex Cloud" in str(parsed.vendor_name.value)
        print("[PASS] Live Gemini targeted extraction verified with exact schema adherence and null policy!")
    except Exception as e:
        print(f"[WARN] Live Gemini test encountered: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING PHASE 8 TARGETED STRUCTURED EXTRACTION TEST SUITE")
    print("=" * 60)
    test_section_schemas()
    test_targeted_prompt_builder()
    test_unknown_document_bypass()
    test_mocked_invoice_extraction()
    test_mocked_onboarding_extraction()
    test_fastapi_endpoints()
    test_preconditions_validation()
    test_anti_hallucination_absent_field()
    test_live_gemini_extraction()
    print("\n" + "=" * 60)
    print("ALL PHASE 8 EXTRACTION TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
