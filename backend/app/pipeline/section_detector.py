import json
import logging
import os
import uuid
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.pipeline.types import (
    BoundingBox,
    OCRDocumentResult,
    OCRBlock,
    DocumentType,
    InvoiceSectionType,
    OnboardingSectionType,
    GeminiSectionDetectionOutput,
    GeminiRawSection,
    DocumentSection,
    DocumentSectionResult,
)
from app.pipeline.preprocessing import BASE_TMP_DIR, _ensure_clean_dir

logger = logging.getLogger(__name__)

# Allowed section name whitelists
INVOICE_SECTION_WHITELIST = {item.value for item in InvoiceSectionType}
ONBOARDING_SECTION_WHITELIST = {item.value for item in OnboardingSectionType}


def _get_gemini_service():
    """Lazily load gemini_service to avoid circular import issues across packages."""
    from app.services.gemini import gemini_service
    return gemini_service


def compute_blocks_bounding_box(blocks: List[OCRBlock]) -> Optional[BoundingBox]:
    """Compute the union bounding box enclosing a collection of OCR blocks."""
    if not blocks:
        return None

    min_x = min(b.bbox.x for b in blocks)
    min_y = min(b.bbox.y for b in blocks)
    max_x = max(b.bbox.x + b.bbox.width for b in blocks)
    max_y = max(b.bbox.y + b.bbox.height for b in blocks)

    return BoundingBox(
        x=min_x,
        y=min_y,
        width=max(1, max_x - min_x),
        height=max(1, max_y - min_y),
    )


class SectionDetector:
    """
    Phase 7 — Section Detection Layer.
    Consumes OCR output and Document Classification result to identify
    logical regions of a document prior to Phase 8 structured field extraction.
    """

    def __init__(self):
        pass

    def build_section_prompt(self, ocr_result: OCRDocumentResult, document_type: str) -> str:
        """
        Build controlled, structure-analyzer prompt for Gemini.
        Instructs model strictly to identify sections and forbid field extraction.
        """
        if document_type == "invoice":
            allowed_sections = ", ".join(sorted(INVOICE_SECTION_WHITELIST))
            type_context = (
                "The document has been verified as an INVOICE. "
                f"Supported section names are: {allowed_sections}.\n"
                "Common sections include:\n"
                "- vendor_information: Seller/supplier details, company name, address, tax ID/VAT\n"
                "- customer_information: Bill-to / ship-to client details, name, address\n"
                "- invoice_metadata: Invoice number, issue date, due date, PO number\n"
                "- line_items: Table/list of purchased goods, quantities, unit prices, descriptions\n"
                "- payment_information: Remittance bank details, wire instructions, payment terms\n"
                "- tax_information: Breakdown of sales tax, GST/HST, VAT percentages\n"
                "- notes: Additional terms, return policy, footer notes, comments\n"
                "- unknown: Any other unrecognized section"
            )
        elif document_type == "onboarding_form":
            allowed_sections = ", ".join(sorted(ONBOARDING_SECTION_WHITELIST))
            type_context = (
                "The document has been verified as an ONBOARDING FORM. "
                f"Supported section names are: {allowed_sections}.\n"
                "Common sections include:\n"
                "- personal_information: Legal name, date of birth, SSN, marital status\n"
                "- contact_information: Residential address, phone numbers, personal email\n"
                "- employment_information: Job title, department, start date, employee ID, manager\n"
                "- emergency_contact: Emergency contact names, relationship, phone numbers\n"
                "- identity_documents: Passport, driver license, work authorization details\n"
                "- bank_details: Direct deposit details, routing number, account number\n"
                "- agreements: Attestations, background check consent, signed declarations\n"
                "- notes: Miscellaneous instructions or candidate notes\n"
                "- unknown: Any other unrecognized section"
            )
        else:
            allowed_sections = "unknown"
            type_context = "Supported section name: unknown."

        # Assemble layout-aware representation with block indices for spatial attribution
        page_representations = []
        for page in ocr_result.pages:
            lines = [f"=== PAGE {page.page_number} (Dimensions: {page.width}x{page.height}) ==="]
            for b in page.blocks:
                lines.append(f"[Block #{b.block_index}] {b.text.strip()}")
            page_representations.append("\n".join(lines))

        ocr_content = "\n\n".join(page_representations)
        if len(ocr_content) > 10000:
            ocr_content = ocr_content[:10000] + "\n... [Remaining content truncated for length]"

        prompt = f"""You are a document structure analyzer.
Your task: Identify sections only.
Do NOT extract fields.
Do NOT summarize.
Do NOT classify.
Only identify regions.
Return structured JSON.

DOCUMENT CONTEXT:
{type_context}

STRICT SECTION DETECTION RULES:
1. ONLY identify logical regions/sections. Do NOT extract specific fields (such as invoice number, total amount, taxes, applicant name, dates).
2. For each detected section, assign the exact matching `section_name` from the supported list above. If a region does not clearly match, use "unknown".
3. Return the exact contiguous raw text comprising that section in `text`.
4. Include the `page_number` where the section is located.
5. Provide a confidence score between 0.0 and 1.0 in `confidence`.
6. Include the list of matching block indices in `block_ids` (e.g. [0, 1, 2]).

DOCUMENT OCR CONTENT:
{ocr_content}
"""
        return prompt

    def detect_sections(
        self,
        ocr_result: OCRDocumentResult,
        classification_type: str,
    ) -> DocumentSectionResult:
        """
        Execute section detection.
        If document_type == 'unknown', returns empty list [] without invoking Gemini.
        """
        if not ocr_result:
            raise ValueError("No OCR document result provided.")

        normalized_type = str(classification_type).strip().lower()

        # Handle 'unknown' document type: return empty sections list immediately
        if normalized_type not in ("invoice", "onboarding_form"):
            logger.info(
                f"Document '{ocr_result.document_id}' has document_type '{normalized_type}'. "
                "Returning empty sections list without invoking LLM."
            )
            empty_result = DocumentSectionResult(
                document_id=ocr_result.document_id,
                document_type=normalized_type,
                sections=[],
            )
            self._save_sections_artifact(ocr_result.document_id, empty_result)
            return empty_result

        # Build prompt
        prompt = self.build_section_prompt(ocr_result, normalized_type)

        # Call Gemini structured output
        gemini_service = _get_gemini_service()
        gemini_output: GeminiSectionDetectionOutput = gemini_service.detect_sections(prompt)

        # Build block lookup map for fast bounding box computation: (page_num, block_idx) -> OCRBlock
        block_map: Dict[tuple, OCRBlock] = {}
        for page in ocr_result.pages:
            for b in page.blocks:
                block_map[(page.page_number, b.block_index)] = b

        # Determine whitelist based on document type
        whitelist = INVOICE_SECTION_WHITELIST if normalized_type == "invoice" else ONBOARDING_SECTION_WHITELIST

        validated_sections: List[DocumentSection] = []

        for raw_sec in gemini_output.sections:
            sec_name = raw_sec.section_name.strip().lower()
            # Validate section name against whitelist
            if sec_name not in whitelist:
                logger.warning(
                    f"Invalid section name '{raw_sec.section_name}' for type '{normalized_type}'. Mapping to 'unknown'."
                )
                sec_name = "unknown"

            # Resolve blocks and bounding box
            matched_blocks: List[OCRBlock] = []
            valid_block_ids: List[int] = []
            for b_id in raw_sec.block_ids:
                key = (raw_sec.page_number, b_id)
                if key in block_map:
                    matched_blocks.append(block_map[key])
                    valid_block_ids.append(b_id)

            bbox = compute_blocks_bounding_box(matched_blocks)

            section_item = DocumentSection(
                section_id=str(uuid.uuid4()),
                document_id=ocr_result.document_id,
                section_name=sec_name,
                page_number=raw_sec.page_number,
                text=raw_sec.text,
                confidence=raw_sec.confidence,
                block_ids=valid_block_ids,
                bbox=bbox,
            )
            validated_sections.append(section_item)

        result = DocumentSectionResult(
            document_id=ocr_result.document_id,
            document_type=normalized_type,
            sections=validated_sections,
        )

        # Save artifact to disk
        self._save_sections_artifact(ocr_result.document_id, result)

        return result

    def _save_sections_artifact(self, document_id: str, result: DocumentSectionResult) -> str:
        """Persist sections.json artifact in processing directory."""
        doc_dir = os.path.join(BASE_TMP_DIR, document_id)
        os.makedirs(doc_dir, exist_ok=True)
        sections_path = os.path.join(doc_dir, "sections.json")

        with open(sections_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)

        logger.info(f"Saved section detection artifact to: {sections_path}")
        return sections_path


# Global instance
section_detector = SectionDetector()


def detect_sections_for_document(ocr_result: OCRDocumentResult, classification_type: str) -> DocumentSectionResult:
    """Convenience functional wrapper for section detection stage."""
    return section_detector.detect_sections(ocr_result, classification_type)
