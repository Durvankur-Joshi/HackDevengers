import json
import logging
import os
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Type

from app.core.config import settings
from app.pipeline.types import (
    DocumentSection,
    DocumentSectionResult,
    ExtractedField,
    DocumentExtractionResult,
    ExtractedFieldProvenance,
    ExtractedNumberProvenance,
    ExtractedBoolProvenance,
    # Invoice schemas
    VendorInfoExtraction,
    CustomerInfoExtraction,
    InvoiceMetadataExtraction,
    LineItemExtraction,
    LineItemsExtraction,
    TaxInfoExtraction,
    PaymentInfoExtraction,
    NotesExtraction,
    # Onboarding schemas
    PersonalInfoExtraction,
    ContactInfoExtraction,
    EmploymentInfoExtraction,
    EmergencyContactExtraction,
    IdentityDocItem,
    IdentityDocsExtraction,
    BankDetailsExtraction,
    AgreementItem,
    AgreementsExtraction,
    OnboardingNotesExtraction,
)
from app.pipeline.preprocessing import BASE_TMP_DIR

logger = logging.getLogger(__name__)


def _get_gemini_service():
    """Lazily load gemini_service to avoid circular import issues across packages."""
    from app.services.gemini import gemini_service
    return gemini_service


# Section to Schema mapping
INVOICE_SECTION_SCHEMAS: Dict[str, Tuple[Type, List[str]]] = {
    "vendor_information": (
        VendorInfoExtraction,
        ["vendor_name", "vendor_address", "vendor_email", "vendor_phone", "vendor_tax_id"],
    ),
    "customer_information": (
        CustomerInfoExtraction,
        ["customer_name", "customer_address", "customer_email", "customer_phone", "customer_tax_id"],
    ),
    "invoice_metadata": (
        InvoiceMetadataExtraction,
        ["invoice_number", "invoice_date", "due_date", "currency", "purchase_order_number"],
    ),
    "line_items": (
        LineItemsExtraction,
        ["items (description, quantity, unit_price, tax_rate, line_total)"],
    ),
    "tax_information": (
        TaxInfoExtraction,
        ["subtotal", "tax_amount", "tax_rate", "discount", "total"],
    ),
    "payment_information": (
        PaymentInfoExtraction,
        ["payment_method", "bank_name", "account_number", "ifsc", "payment_reference"],
    ),
    "notes": (
        NotesExtraction,
        ["notes"],
    ),
}

ONBOARDING_SECTION_SCHEMAS: Dict[str, Tuple[Type, List[str]]] = {
    "personal_information": (
        PersonalInfoExtraction,
        ["full_name", "date_of_birth", "gender", "nationality"],
    ),
    "contact_information": (
        ContactInfoExtraction,
        ["email", "phone", "address", "city", "state", "postal_code"],
    ),
    "employment_information": (
        EmploymentInfoExtraction,
        ["employee_id", "designation", "department", "joining_date", "employment_type"],
    ),
    "emergency_contact": (
        EmergencyContactExtraction,
        ["name", "relationship", "phone", "email"],
    ),
    "identity_documents": (
        IdentityDocsExtraction,
        ["documents (document_type, document_number, issue_date, expiry_date)"],
    ),
    "bank_details": (
        BankDetailsExtraction,
        ["account_holder_name", "bank_name", "account_number", "ifsc"],
    ),
    "agreements": (
        AgreementsExtraction,
        ["agreements (agreement_type, accepted, date)"],
    ),
    "notes": (
        OnboardingNotesExtraction,
        ["notes"],
    ),
}


class DocumentExtractor:
    """
    Phase 8 — Targeted Structured AI Extraction Stage.
    Consumes DocumentSectionResult and extracts typed fields targeted per section.
    Enforces the rule: DO NOT send the entire document or entire OCR to Gemini.
    """

    def __init__(self):
        pass

    def build_targeted_section_prompt(
        self,
        document_type: str,
        section_name: str,
        section_text: str,
        page_number: int,
        field_names: List[str],
    ) -> str:
        """
        Construct targeted extraction prompt containing strictly the section text
        and explicit negative instructions forbidding fabrication and arithmetic corrections.
        """
        fields_str = ", ".join(field_names)
        prompt = f"""You are a precision structured field extractor for document sections.
Your task: Extract typed fields from the section text below.
DOCUMENT TYPE: {document_type}
SECTION NAME: {section_name} (Page {page_number})

CRITICAL EXTRACTION RULES:
1. Extract only fields relevant to this section: {fields_str}.
2. DO NOT invent, guess, fabricate, or hallucinate missing values.
3. If a field is not explicitly present in the section text, return null for its value, confidence, and source_text.
4. For each extracted value, include:
   - 'value': the extracted value (or null)
   - 'confidence': confidence score between 0.0 and 1.0 reflecting certainty (or null if missing)
   - 'source_text': the short exact excerpt from the section where this was found (or null)
5. Do NOT perform arithmetic recalculation or validation (e.g. do not recalculate subtotal + tax = total).
6. Return strictly valid structured JSON adhering to the response schema.

TARGETED SECTION TEXT:
\"\"\"{section_text}\"\"\"
"""
        return prompt

    def extract_document(
        self,
        section_result: DocumentSectionResult,
    ) -> DocumentExtractionResult:
        """
        Execute targeted structured extraction on each detected section.
        If document_type == 'unknown', returns skipped payload immediately.
        """
        if not section_result:
            raise ValueError("No section result provided for extraction.")

        doc_id = section_result.document_id
        doc_type = str(section_result.document_type).strip().lower()
        now_iso = datetime.utcnow().isoformat() + "Z"

        # Check unsupported document type rule
        if doc_type not in ("invoice", "onboarding_form"):
            logger.info(
                f"Document '{doc_id}' has unsupported document_type '{doc_type}'. "
                "Skipping structured extraction."
            )
            skipped_result = DocumentExtractionResult(
                document_id=doc_id,
                document_type=doc_type,
                status="skipped",
                reason="Unsupported document type",
                fields=[],
                section_data={},
                extracted_at=now_iso,
                metadata={"document_type": doc_type, "sections_received": len(section_result.sections)},
            )
            self._save_extraction_artifact(doc_id, skipped_result)
            return skipped_result

        schema_map = INVOICE_SECTION_SCHEMAS if doc_type == "invoice" else ONBOARDING_SECTION_SCHEMAS

        all_fields: List[ExtractedField] = []
        structured_section_data: Dict[str, Any] = {}
        sections_processed_count = 0
        failed_sections: List[str] = []

        gemini_service = _get_gemini_service()

        for section in section_result.sections:
            sec_name = section.section_name.strip().lower()
            if sec_name not in schema_map:
                logger.info(f"Skipping section '{sec_name}' (not registered in {doc_type} extraction schemas)")
                continue

            sec_text = (section.text or "").strip()
            if not sec_text or len(sec_text) < 5:
                logger.info(f"Skipping empty or meaningless text for section '{sec_name}'")
                continue

            schema_cls, field_names = schema_map[sec_name]
            prompt = self.build_targeted_section_prompt(
                document_type=doc_type,
                section_name=sec_name,
                section_text=sec_text,
                page_number=section.page_number,
                field_names=field_names,
            )

            try:
                # Targeted Gemini Call per section
                extracted_data = gemini_service.extract_section_data(
                    prompt=prompt,
                    response_schema=schema_cls,
                )
                data_dict = extracted_data.model_dump()
                structured_section_data[sec_name] = data_dict
                sections_processed_count += 1

                # Convert into canonical ExtractedField provenance records
                self._convert_to_extracted_fields(
                    sec_name=sec_name,
                    section_id=section.section_id,
                    page_number=section.page_number,
                    data_dict=data_dict,
                    out_fields=all_fields,
                )

            except Exception as e:
                logger.error(f"Error during targeted extraction of section '{sec_name}' for doc '{doc_id}': {e}")
                failed_sections.append(sec_name)
                # Continue processing remaining sections to provide partial extraction results
                continue

        final_result = DocumentExtractionResult(
            document_id=doc_id,
            document_type=doc_type,
            status="extracted",
            reason=None,
            fields=all_fields,
            section_data=structured_section_data,
            extracted_at=now_iso,
            metadata={
                "model": settings.GEMINI_MODEL,
                "sections_processed": sections_processed_count,
                "failed_sections": failed_sections,
                "total_fields_extracted": len(all_fields),
            },
        )

        # Persist extraction.json artifact
        self._save_extraction_artifact(doc_id, final_result)

        return final_result

    def _convert_to_extracted_fields(
        self,
        sec_name: str,
        section_id: Optional[str],
        page_number: int,
        data_dict: Dict[str, Any],
        out_fields: List[ExtractedField],
    ):
        """Transform structured section dictionary into standardized ExtractedField items."""
        # Special handling for line_items
        if sec_name == "line_items" and "items" in data_dict:
            items = data_dict.get("items") or []
            for idx, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                # Line item sub-fields
                for prop in ["description", "quantity", "unit_price", "tax_rate", "line_total"]:
                    val = item.get(prop)
                    out_fields.append(
                        ExtractedField(
                            id=str(uuid.uuid4()),
                            section_id=section_id,
                            field_name=f"line_item_{idx}_{prop}",
                            field_value=val,
                            confidence=item.get("confidence"),
                            source="gemini",
                            source_text=item.get("source_text"),
                            section_name=sec_name,
                            page_number=page_number,
                        )
                    )
            return

        # Special handling for identity_documents
        if sec_name == "identity_documents" and "documents" in data_dict:
            docs = data_dict.get("documents") or []
            for idx, doc_item in enumerate(docs, start=1):
                if not isinstance(doc_item, dict):
                    continue
                for prop in ["document_type", "document_number", "issue_date", "expiry_date"]:
                    val = doc_item.get(prop)
                    out_fields.append(
                        ExtractedField(
                            id=str(uuid.uuid4()),
                            section_id=section_id,
                            field_name=f"id_doc_{idx}_{prop}",
                            field_value=val,
                            confidence=doc_item.get("confidence"),
                            source="gemini",
                            source_text=doc_item.get("source_text"),
                            section_name=sec_name,
                            page_number=page_number,
                        )
                    )
            return

        # Special handling for agreements
        if sec_name == "agreements" and "agreements" in data_dict:
            agreements = data_dict.get("agreements") or []
            for idx, agree_item in enumerate(agreements, start=1):
                if not isinstance(agree_item, dict):
                    continue
                for prop in ["agreement_type", "accepted", "date"]:
                    val = agree_item.get(prop)
                    out_fields.append(
                        ExtractedField(
                            id=str(uuid.uuid4()),
                            section_id=section_id,
                            field_name=f"agreement_{idx}_{prop}",
                            field_value=val,
                            confidence=agree_item.get("confidence"),
                            source="gemini",
                            source_text=agree_item.get("source_text"),
                            section_name=sec_name,
                            page_number=page_number,
                        )
                    )
            return

        # Standard scalar fields with ExtractedFieldProvenance
        for field_name, field_obj in data_dict.items():
            if isinstance(field_obj, dict):
                val = field_obj.get("value")
                conf = field_obj.get("confidence")
                src_txt = field_obj.get("source_text")
            else:
                val = field_obj
                conf = None
                src_txt = None

            out_fields.append(
                ExtractedField(
                    id=str(uuid.uuid4()),
                    section_id=section_id,
                    field_name=field_name,
                    field_value=val,
                    confidence=conf,
                    source="gemini",
                    source_text=src_txt,
                    section_name=sec_name,
                    page_number=page_number,
                )
            )

    def _save_extraction_artifact(self, document_id: str, result: DocumentExtractionResult) -> str:
        """Persist extraction.json artifact in processing directory."""
        doc_dir = os.path.join(BASE_TMP_DIR, document_id)
        os.makedirs(doc_dir, exist_ok=True)
        extraction_path = os.path.join(doc_dir, "extraction.json")

        with open(extraction_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)

        logger.info(f"Saved extraction artifact to: {extraction_path}")
        return extraction_path


# Global instance
document_extractor = DocumentExtractor()


def extract_document_fields(section_result: DocumentSectionResult) -> DocumentExtractionResult:
    """Convenience functional wrapper for extraction stage."""
    return document_extractor.extract_document(section_result)
