import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.core.config import settings
from app.pipeline.types import (
    DocumentSummaryResult,
    DocumentValidationResult,
    ExtractedField,
    GeminiDocumentSummaryOutput,
    ValidationStatusEnum,
)
from app.services.gemini import gemini_service, GeminiService
from app.services.supabase import supabase_service

logger = logging.getLogger(__name__)

# Sensitive field keywords that should be masked in summary context
SENSITIVE_FIELD_SUBSTRINGS = (
    "account_number",
    "bank_account",
    "ifsc",
    "routing_number",
    "tax_id",
    "ssn",
    "pan_number",
    "aadhaar",
    "passport",
    "identity_doc",
)


class DocumentSummarizer:
    """
    Intelligent, grounded document summarizer consuming validated structured pipeline data.
    Strictly forbids raw OCR dumping, sensitive data leakage, and hallucinated facts.
    """

    def __init__(
        self,
        processing_base_dir: Optional[Union[str, Path]] = None,
        gemini: Optional[GeminiService] = None,
    ):
        if processing_base_dir is not None:
            self.base_dir = Path(processing_base_dir)
        else:
            self.base_dir = Path(__file__).resolve().parent.parent.parent / "tmp" / "processing"
        self.gemini = gemini or gemini_service

    def build_summary_context(
        self,
        document_type: str,
        fields: List[ExtractedField],
        validation_issues: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Builds a compact, sanitized structured context dictionary from validated fields.
        Masks raw sensitive values while noting presence.
        """
        field_records = []
        conflicts_present = []

        for f in fields:
            fname = f.field_name.lower()
            raw_val = f.field_value
            norm_val = f.normalized_value
            display_val = norm_val if norm_val is not None else raw_val

            # Sensitive data masking: note presence without exposing raw identifiers
            if any(sens in fname for sens in SENSITIVE_FIELD_SUBSTRINGS):
                if display_val is not None and str(display_val).strip() != "":
                    display_val = "[PRESENT - SENSITIVE VALUE PROTECTED]"
                else:
                    display_val = None

            status = f.validation_status or ValidationStatusEnum.VALID.value
            if status == ValidationStatusEnum.CONFLICT.value:
                conflicts_present.append(f.field_name)

            field_records.append({
                "field_name": f.field_name,
                "value": display_val,
                "normalized_value": display_val,
                "validation_status": status,
                "validation_message": f.validation_message,
                "section": f.section_name,
            })

        # Sanitize validation issues
        clean_issues = []
        for issue in (validation_issues or []):
            clean_issues.append({
                "field_name": issue.get("field_name"),
                "status": issue.get("status"),
                "message": issue.get("message"),
            })

        return {
            "document_type": document_type,
            "fields": field_records,
            "validation_issues": clean_issues,
            "conflicts_detected": conflicts_present,
        }

    def _sanitize_context_for_llm(self, validation_result: DocumentValidationResult) -> Dict[str, Any]:
        """Convenience method to sanitize context from a DocumentValidationResult."""
        return self.build_summary_context(
            document_type=validation_result.document_type,
            fields=validation_result.fields,
            validation_issues=validation_result.validation_issues,
        )

    def build_prompt(self, document_type: str, context: Dict[str, Any]) -> str:
        """
        Generates strict, factual, zero-hallucination prompt for Gemini summarization.
        """
        context_json = json.dumps(context, indent=2, ensure_ascii=False)

        if document_type == "invoice":
            type_guidelines = """INVOICE SUMMARIZATION GUIDELINES:
- Clearly capture the primary business entities: vendor, customer, invoice number, invoice date, due date.
- Summarize financial figures: total amount, currency, tax amount, and subtotal where present.
- Mention payment terms or method if stated.
- Note any validation issues or calculation discrepancies directly in the review items.
- If conflicting invoice numbers or totals exist, explicitly state: "Conflicting invoice numbers/totals were detected and require human review." DO NOT choose one arbitrarily."""
        elif document_type == "onboarding_form":
            type_guidelines = """ONBOARDING FORM SUMMARIZATION GUIDELINES:
- Summarize candidate/employee identity: full name, department, designation, and expected joining date if present.
- Note availability of contact info, emergency contact, bank details, and identity documents (e.g. state "Bank details are provided", DO NOT expose actual account or tax numbers).
- Note any missing required items or items requiring review in the review items list.
- If conflicts exist, note them without choosing an arbitrary value."""
        else:
            type_guidelines = "General document summarization: focus strictly on extracted grounded facts."

        return f"""You are an expert executive document intelligence analyst.
Your task is to generate a concise, factual, human-readable executive summary of the document based STRICTLY on the structured, validated data provided below.

{type_guidelines}

CRITICAL ANTI-HALLUCINATION & INTEGRITY RULES:
1. ONLY describe facts directly present in the structured fields. NEVER invent names, numbers, dates, or terms.
2. If a field value is null or absent, DO NOT invent a value. Simply omit it or note it as missing if required.
3. If a field has validation_status "conflict", DO NOT arbitrarily pick one value. Explicitly state that a conflict was detected.
4. Keep the executive summary concise (2 to 4 sentences).
5. Provide up to 5 key_points (concise factual bullet points).
6. Provide up to 5 review_items (flagged validation issues, discrepancies, or missing required fields). If there are no issues, return an empty array for review_items.
7. DO NOT generate numerical quality scores or confidence ratings.

STRUCTURED DOCUMENT CONTEXT:
{context_json}
"""

    def generate_summary(
        self,
        document_id: str,
        document_type: Optional[str] = None,
        fields: Optional[List[ExtractedField]] = None,
        validation_result: Optional[DocumentValidationResult] = None,
    ) -> DocumentSummaryResult:
        """
        Generates grounded executive summary, key points, and review items for a document.
        """
        doc_dir = Path(self.base_dir) / document_id
        now_iso = datetime.utcnow().isoformat()

        if isinstance(fields, DocumentValidationResult):
            validation_result = fields
            fields = validation_result.fields

        # Step 1: Load validation result or extraction artifact if fields not provided
        if fields is None or validation_result is None:
            val_file = doc_dir / "validation.json"
            if val_file.exists():
                try:
                    with open(val_file, "r", encoding="utf-8") as f:
                        vdata = json.load(f)
                    if validation_result is None:
                        validation_result = DocumentValidationResult.model_validate(vdata)
                    if fields is None:
                        fields = validation_result.fields
                    if not document_type:
                        document_type = validation_result.document_type
                except Exception as e:
                    logger.warning(f"Error loading validation.json for doc {document_id}: {e}")

        # Fallback to extraction.json if validation.json not found
        if fields is None:
            ext_file = doc_dir / "extraction.json"
            if ext_file.exists():
                try:
                    with open(ext_file, "r", encoding="utf-8") as f:
                        edata = json.load(f)
                    fields = [ExtractedField.model_validate(item) for item in edata.get("fields", [])]
                    if not document_type:
                        document_type = edata.get("document_type")
                except Exception as e:
                    logger.warning(f"Error loading extraction.json for doc {document_id}: {e}")

        fields = fields or []
        doc_type = (document_type or "unknown").strip().lower()

        # Step 2: Handle Unknown Document Type
        if doc_type == "unknown":
            logger.info(f"Skipping structured summary for document {document_id} of unknown type.")
            result = DocumentSummaryResult(
                document_id=document_id,
                document_type="unknown",
                status="skipped",
                summary="Summary generation is unavailable for unknown document types.",
                key_points=[],
                review_items=[],
                generated_at=now_iso,
                metadata={"message": "Unsupported document type for structured summary."},
            )
            self._save_summary(doc_dir, document_id, result)
            return result

        # Step 3: Check empty fields
        if not fields:
            logger.warning(f"No extracted fields available to summarize for document {document_id}.")
            result = DocumentSummaryResult(
                document_id=document_id,
                document_type=doc_type,
                status="skipped",
                summary="No extracted fields available to generate a document summary.",
                key_points=[],
                review_items=["Document has not completed field extraction."],
                generated_at=now_iso,
                metadata={"message": "No fields extracted."},
            )
            self._save_summary(doc_dir, document_id, result)
            return result

        # Step 4: Build Context & Prompt
        issues = validation_result.validation_issues if validation_result else []
        context = self.build_summary_context(doc_type, fields, issues)
        prompt = self.build_prompt(doc_type, context)

        # Step 5: Execute Gemini Call
        try:
            ai_output = self.gemini.generate_document_summary(prompt)
        except Exception as e:
            logger.error(f"Gemini summary generation failed for doc {document_id}: {e}")
            raise

        result = DocumentSummaryResult(
            document_id=document_id,
            document_type=doc_type,
            status="summarized",
            summary=ai_output.summary,
            key_points=ai_output.key_points[:settings.SUMMARY_MAX_KEY_POINTS],
            review_items=ai_output.review_items[:settings.SUMMARY_MAX_REVIEW_ITEMS],
            generated_at=now_iso,
            metadata={
                "fields_evaluated": len(fields),
                "issues_count": len(issues),
                "key_points_count": len(ai_output.key_points),
                "review_items_count": len(ai_output.review_items),
            },
        )

        self._save_summary(doc_dir, document_id, result)
        return result

    def _save_summary(self, doc_dir: Path, document_id: str, result: DocumentSummaryResult):
        """Persists summary artifact to disk and updates documents.summary in database."""
        try:
            doc_dir.mkdir(parents=True, exist_ok=True)
            summary_file = doc_dir / "summary.json"
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)
            logger.info(f"Saved summary artifact for {document_id} to {summary_file}")
        except Exception as e:
            logger.error(f"Failed to write summary.json for {document_id}: {e}")

        # Persist summary string into documents table in Supabase
        if result.status == "summarized" and result.summary:
            try:
                if supabase_service.is_configured():
                    supabase_service.update_document_summary(document_id, result.summary)
            except Exception as db_err:
                logger.warning(f"Could not persist summary to Supabase for {document_id}: {db_err}")

    summarize_document = generate_summary


document_summarizer = DocumentSummarizer()
