import logging
from datetime import datetime
from typing import Optional, List

from app.core.config import settings
from app.pipeline.types import (
    OCRDocumentResult,
    DocumentType,
    GeminiClassificationOutput,
    DocumentClassificationResult,
)

logger = logging.getLogger(__name__)

MAX_PROMPT_TEXT_LENGTH = 7500


def _get_gemini_service():
    """Lazily load gemini_service to avoid circular import between services and pipeline packages."""
    from app.services.gemini import gemini_service
    return gemini_service


class DocumentClassifier:
    """
    Dedicated Document Classifier stage.
    Consumes structured OCRDocumentResult and performs semantic archetype classification
    using Google Gemini, strictly enforcing the confidence threshold and 'unknown' fallback.
    """

    def __init__(self, confidence_threshold: Optional[float] = None):
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else settings.CLASSIFICATION_CONFIDENCE_THRESHOLD
        )

    def build_classification_input(self, ocr_result: OCRDocumentResult) -> str:
        """
        Build a concise, layout-grounded text representation for Gemini classification.
        Constrains payload size while preserving page demarcations and key visual blocks.
        """
        pages = ocr_result.pages or []
        page_count = len(pages)

        # Decide which pages to include for multi-page documents
        if page_count <= 3:
            selected_pages = pages
            omitted_pages = False
        else:
            # First 2 pages and the last page (often contains totals or signatures)
            selected_pages = [pages[0], pages[1], pages[-1]]
            omitted_pages = True

        sections: List[str] = []
        sections.append(f"TOTAL DOCUMENT PAGES: {page_count}")
        sections.append(f"AVERAGE OCR QUALITY CONFIDENCE: {ocr_result.metadata.average_confidence or 'N/A'}%")

        for idx, page in enumerate(selected_pages):
            sections.append(f"\n--- PAGE {page.page_number} OF {page_count} (Resolution: {page.width}x{page.height}px) ---")
            
            # Select up to top 20 blocks for layout context
            page_blocks = page.blocks or []
            if page_blocks:
                block_lines = [f"[Block {b.block_index} | Pos ({b.bbox.x},{b.bbox.y})]: {b.text}" for b in page_blocks[:20]]
                sections.append("\n".join(block_lines))
            elif page.text:
                sections.append(page.text[:1200])

            if idx == 1 and omitted_pages:
                sections.append(f"\n[... Intermediate pages 3 to {page_count - 1} omitted for brevity ...]")

        full_content = "\n".join(sections)
        if len(full_content) > MAX_PROMPT_TEXT_LENGTH:
            full_content = full_content[:MAX_PROMPT_TEXT_LENGTH] + "\n[... Content truncated to token limit ...]"

        prompt = f"""You are a specialized document classification intelligence system in an automated document processing pipeline.

TASK:
Analyze the OCR layout text extracted from a document and classify it into EXACTLY ONE of the following document archetypes:
1. "invoice"
2. "onboarding_form"
3. "unknown"

DOCUMENT ARCHETYPE DEFINITIONS:
- "invoice": Commercial invoices, bills, utility invoices, purchase orders, sales receipts, and payment requests. Key characteristics: vendor details, recipient/client details, invoice numbers, issue/due dates, line-item pricing, subtotal, tax calculations, and grand total payment amounts.
- "onboarding_form": Structured personnel or client registration forms, employee intake sheets, enrollment declarations, membership forms. Key characteristics: structured personal intake fields (Full Name, DOB, SSN/National ID), residential address, emergency contacts, employee department/role, and applicant declaration checkboxes or signatures.
- "unknown": ANY document that does not explicitly match "invoice" or "onboarding_form".
  * CRITICAL RULE 1: Resumes, CVs, portfolios, and job applicant biographies MUST BE CLASSIFIED AS "unknown". They are NOT onboarding forms, even if they mention work history, contact information, or education.
  * CRITICAL RULE 2: Passports, ID cards, legal contracts, business memos, correspondence letters, menus, and academic certificates are NOT invoices or onboarding forms; they MUST be classified as "unknown".
  * CRITICAL RULE 3: If the document is ambiguous, has unreadable/noisy text, or lacks the complete functional structure of an invoice or onboarding form, classify as "unknown".

INSTRUCTIONS:
- Analyze solely the provided OCR text and spatial layout cues.
- Return a confidence score between 0.0 and 1.0 reflecting your certainty.
- Provide a list of 2 to 4 concise, factual evidence points justifying your decision.
- Never output document types other than "invoice", "onboarding_form", or "unknown".

DOCUMENT OCR TEXT CONTENT:
{full_content}
"""
        return prompt

    def classify(self, ocr_result: OCRDocumentResult) -> DocumentClassificationResult:
        """
        Execute end-to-end document classification with thresholding and fallback.
        """
        if not ocr_result:
            raise ValueError("No OCR document result provided for classification.")

        # Build controlled classification input prompt
        prompt = self.build_classification_input(ocr_result)

        # Call Gemini semantic classifier
        gemini_output: GeminiClassificationOutput = _get_gemini_service().classify_content(prompt)

        raw_type = gemini_output.document_type
        assigned_type = raw_type
        confidence = gemini_output.confidence
        evidence = list(gemini_output.evidence)

        # Enforce configurable confidence threshold (Section 10)
        threshold = self.confidence_threshold
        below_threshold = False

        if assigned_type != DocumentType.UNKNOWN and confidence < threshold:
            logger.info(
                f"Document '{ocr_result.document_id}' classification '{assigned_type.value}' "
                f"confidence {confidence:.2f} is below threshold {threshold:.2f}. Falling back to 'unknown'."
            )
            assigned_type = DocumentType.UNKNOWN
            below_threshold = True
            evidence.append(
                f"Confidence ({confidence:.2f}) was below threshold ({threshold:.2f}); marked as unknown."
            )

        now_iso = datetime.utcnow().isoformat() + "Z"

        return DocumentClassificationResult(
            document_id=ocr_result.document_id,
            document_type=assigned_type,
            confidence=confidence,
            evidence=evidence,
            ocr_average_confidence=ocr_result.metadata.average_confidence,
            classified_at=now_iso,
            metadata={
                "model": settings.GEMINI_MODEL,
                "confidence_threshold": threshold,
                "raw_document_type": raw_type.value,
                "below_threshold": below_threshold,
                "page_count": ocr_result.page_count,
            },
        )


# Global default instance
document_classifier = DocumentClassifier()


def classify_document(ocr_result: OCRDocumentResult) -> DocumentClassificationResult:
    """Convenience function to classify an OCR document result."""
    return document_classifier.classify(ocr_result)
