import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Set

from app.core.config import settings
from app.pipeline.normalizer import (
    FieldNormalizer,
    normalize_date,
    normalize_number,
    normalize_email,
    normalize_phone,
)
from app.pipeline.types import (
    ExtractedField,
    DocumentValidationSummary,
    DocumentValidationResult,
    ValidationStatusEnum,
)

# Email regex matching standard RFC 5322 compliant formats
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_email(normalized_email: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validates email format deterministically."""
    if not normalized_email:
        return True, None
    if not EMAIL_REGEX.fullmatch(normalized_email):
        return False, "Email format is invalid."
    return True, None


def validate_phone(normalized_phone: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validates phone number format (between 7 and 15 digits)."""
    if not normalized_phone:
        return True, None
    digits = re.sub(r"[^\d]", "", normalized_phone)
    if len(digits) < 7 or len(digits) > 15:
        return False, "Phone number must contain between 7 and 15 digits."
    return True, None


def validate_date_relationship(
    invoice_date_iso: Optional[str], due_date_iso: Optional[str]
) -> Tuple[bool, Optional[str]]:
    """Validates that due_date is on or after invoice_date."""
    if not invoice_date_iso or not due_date_iso:
        return True, None
    try:
        inv_dt = datetime.strptime(invoice_date_iso, "%Y-%m-%d")
        due_dt = datetime.strptime(due_date_iso, "%Y-%m-%d")
        if due_dt < inv_dt:
            return False, "Due date is earlier than invoice date."
    except ValueError:
        pass
    return True, None


def validate_line_item_math(
    quantity: float, unit_price: float, line_total: float, tolerance: float
) -> Tuple[bool, Optional[str]]:
    """Validates quantity * unit_price == line_total within rounding tolerance."""
    expected = quantity * unit_price
    if abs(expected - line_total) > tolerance:
        return False, "Line item total does not match quantity × unit price."
    return True, None


def validate_invoice_subtotal(
    line_totals: List[float], subtotal: float, tolerance: float
) -> Tuple[bool, Optional[str]]:
    """Validates sum(line_totals) == subtotal within rounding tolerance."""
    if not line_totals:
        return True, None
    expected = sum(line_totals)
    if abs(expected - subtotal) > tolerance:
        return False, "Invoice subtotal does not match the sum of line items."
    return True, None


def validate_invoice_tax(
    subtotal: float, tax_rate: Optional[float], tax_amount: float, tolerance: float
) -> Tuple[bool, Optional[str]]:
    """Validates expected tax amount when rate and subtotal exist."""
    if tax_rate is None or tax_rate <= 0:
        return True, None
    rate = tax_rate / 100.0 if tax_rate > 1.0 else tax_rate
    expected_tax = subtotal * rate
    if abs(expected_tax - tax_amount) > tolerance:
        return False, f"Tax amount does not match expected tax from rate ({tax_rate}%)."
    return True, None


def validate_invoice_total(
    subtotal: float,
    tax_amount: float,
    discount: float,
    total: float,
    tolerance: float,
) -> Tuple[bool, Optional[str]]:
    """Validates subtotal + tax_amount - discount == total within tolerance."""
    expected = subtotal + tax_amount - discount
    if abs(expected - total) > tolerance:
        return False, "Invoice total does not match subtotal + tax - discount."
    return True, None


class DocumentValidator:
    """
    Deterministic validation engine for document extractions.
    Ensures zero AI/Gemini usage in validation logic.
    """

    INVOICE_REQUIRED_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total"]

    def __init__(self, tolerance: Optional[float] = None):
        self.tolerance = tolerance if tolerance is not None else settings.INVOICE_ROUNDING_TOLERANCE

    def normalize_and_validate(
        self,
        document_id: str,
        document_type: str,
        fields: List[ExtractedField],
        section_data: Optional[Dict[str, Any]] = None,
    ) -> DocumentValidationResult:
        """
        Executes normalization and deterministic validation on all fields for the document.
        Does NOT mutate field_value (anti-corruption rule).
        """
        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        section_data = section_data or {}

        # 1. First Pass: Deterministic Normalization for each field
        for field in fields:
            norm_val, is_err, err_msg = FieldNormalizer.normalize_field(field)
            field.normalized_value = norm_val
            field.normalized_at = now_iso

            if field.field_value is None:
                # Field was omitted in source
                field.validation_status = ValidationStatusEnum.VALID.value
                field.validation_message = None
            elif is_err:
                field.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                field.validation_message = err_msg or "Field format is invalid or ambiguous."
            else:
                field.validation_status = ValidationStatusEnum.VALID.value
                field.validation_message = None

        # 2. Conflict Detection across duplicate logical fields
        self._detect_conflicts(fields)

        # 3. Format Validation (email, phone)
        for field in fields:
            fname = field.field_name.lower()
            if "email" in fname and field.normalized_value:
                valid_email, email_err = validate_email(field.normalized_value)
                if not valid_email:
                    field.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                    field.validation_message = email_err

            if "phone" in fname and field.normalized_value:
                valid_phone, phone_err = validate_phone(field.normalized_value)
                if not valid_phone:
                    field.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                    field.validation_message = phone_err

        # 4. Document-Type-Specific Business Rules
        if document_type == "invoice":
            self._validate_invoice(fields, section_data)
        elif document_type == "onboarding_form":
            self._validate_onboarding(fields, section_data)

        # 5. Calculate Document Validation Status & Summary Metrics
        valid_cnt = 0
        needs_review_cnt = 0
        conflict_cnt = 0
        validation_issues: List[Dict[str, Any]] = []

        for f in fields:
            st = f.validation_status or ValidationStatusEnum.VALID.value
            if st == ValidationStatusEnum.VALID.value:
                valid_cnt += 1
            elif st == ValidationStatusEnum.NEEDS_REVIEW.value:
                needs_review_cnt += 1
                validation_issues.append({
                    "field_name": f.field_name,
                    "status": st,
                    "message": f.validation_message,
                    "original_value": f.field_value,
                    "normalized_value": f.normalized_value,
                })
            elif st == ValidationStatusEnum.CONFLICT.value:
                conflict_cnt += 1
                validation_issues.append({
                    "field_name": f.field_name,
                    "status": st,
                    "message": f.validation_message,
                    "original_value": f.field_value,
                    "normalized_value": f.normalized_value,
                })

        summary = DocumentValidationSummary(
            total_fields=len(fields),
            valid_count=valid_cnt,
            needs_review_count=needs_review_cnt,
            conflict_count=conflict_cnt,
        )

        doc_status = "completed" if (needs_review_cnt == 0 and conflict_cnt == 0) else "needs_review"

        return DocumentValidationResult(
            document_id=document_id,
            document_type=document_type,
            document_status=doc_status,
            summary=summary,
            fields=fields,
            validation_issues=validation_issues,
            validated_at=now_iso,
            metadata={
                "rounding_tolerance": self.tolerance,
                "document_type": document_type,
                "issues_count": len(validation_issues),
            },
        )

    def _detect_conflicts(self, fields: List[ExtractedField]):
        """
        Identifies fields with the same logical field_name having differing normalized values.
        Identical normalized values are NOT treated as conflicts.
        """
        # Skip repeating line items from generic single-field conflict check
        grouped: Dict[str, List[ExtractedField]] = {}
        for f in fields:
            fname = f.field_name.lower()
            if fname.startswith("line_item_") or fname.startswith("agreement_") or fname.startswith("identity_doc_"):
                continue
            grouped.setdefault(fname, []).append(f)

        for fname, flist in grouped.items():
            if len(flist) > 1:
                # Collect distinct normalized values (ignoring None)
                distinct_vals = {f.normalized_value for f in flist if f.normalized_value is not None}
                if len(distinct_vals) > 1:
                    for f in flist:
                        f.validation_status = ValidationStatusEnum.CONFLICT.value
                        f.validation_message = f"Multiple conflicting values detected for '{f.field_name}': {sorted(list(distinct_vals))}"

    def _validate_invoice(self, fields: List[ExtractedField], section_data: Dict[str, Any]):
        """Deterministic business validation for invoices."""
        field_map = {f.field_name.lower(): f for f in fields}

        # 1. Required Invoice Fields Check
        for req in self.INVOICE_REQUIRED_FIELDS:
            f = field_map.get(req)
            if not f or f.field_value is None or str(f.field_value).strip() == "":
                if f:
                    f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                    f.validation_message = f"Required invoice field '{req}' is missing."
                else:
                    # Add placeholder field for missing required field
                    missing_field = ExtractedField(
                        field_name=req,
                        field_value=None,
                        normalized_value=None,
                        confidence=1.0,
                        source="validation",
                        source_text=None,
                        section_name="invoice_metadata",
                        page_number=1,
                        validation_status=ValidationStatusEnum.NEEDS_REVIEW.value,
                        validation_message=f"Required invoice field '{req}' is missing.",
                    )
                    fields.append(missing_field)
                    field_map[req] = missing_field

        # 2. Date Relationship (due_date >= invoice_date)
        inv_date_f = field_map.get("invoice_date")
        due_date_f = field_map.get("due_date")
        if inv_date_f and due_date_f and inv_date_f.normalized_value and due_date_f.normalized_value:
            is_valid_date_rel, date_err = validate_date_relationship(
                inv_date_f.normalized_value, due_date_f.normalized_value
            )
            if not is_valid_date_rel:
                due_date_f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                due_date_f.validation_message = date_err

        # 3. Line Items Arithmetic Validation
        # Find all line items either from section_data or flattened fields
        line_item_indices = set()
        for fname in field_map.keys():
            m = re.match(r"^line_item_(\d+)_", fname)
            if m:
                line_item_indices.add(int(m.group(1)))

        line_totals: List[float] = []
        for idx in sorted(list(line_item_indices)):
            qty_f = field_map.get(f"line_item_{idx}_quantity")
            price_f = field_map.get(f"line_item_{idx}_unit_price")
            tot_f = field_map.get(f"line_item_{idx}_line_total")

            if tot_f and tot_f.normalized_value:
                try:
                    line_totals.append(float(tot_f.normalized_value))
                except ValueError:
                    pass

            if qty_f and price_f and tot_f:
                if qty_f.normalized_value and price_f.normalized_value and tot_f.normalized_value:
                    try:
                        q = float(qty_f.normalized_value)
                        p = float(price_f.normalized_value)
                        t = float(tot_f.normalized_value)
                        is_valid_math, math_err = validate_line_item_math(q, p, t, self.tolerance)
                        if not is_valid_math:
                            tot_f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                            tot_f.validation_message = math_err
                    except ValueError:
                        pass

        # 4. Subtotal Validation
        subtotal_f = field_map.get("subtotal")
        subtotal_val: Optional[float] = None
        if subtotal_f and subtotal_f.normalized_value:
            try:
                subtotal_val = float(subtotal_f.normalized_value)
                if line_totals:
                    is_valid_subtot, subtot_err = validate_invoice_subtotal(
                        line_totals, subtotal_val, self.tolerance
                    )
                    if not is_valid_subtot:
                        subtotal_f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                        subtotal_f.validation_message = subtot_err
            except ValueError:
                pass

        # 5. Tax Validation
        tax_amt_f = field_map.get("tax_amount")
        tax_rate_f = field_map.get("tax_rate")
        tax_amt_val: float = 0.0
        if tax_amt_f and tax_amt_f.normalized_value:
            try:
                tax_amt_val = float(tax_amt_f.normalized_value)
                if subtotal_val is not None and tax_rate_f and tax_rate_f.normalized_value:
                    tax_rate_val = float(tax_rate_f.normalized_value)
                    is_valid_tax, tax_err = validate_invoice_tax(
                        subtotal_val, tax_rate_val, tax_amt_val, self.tolerance
                    )
                    if not is_valid_tax:
                        tax_amt_f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                        tax_amt_f.validation_message = tax_err
            except ValueError:
                pass

        # 6. Total Validation
        total_f = field_map.get("total")
        discount_f = field_map.get("discount")
        discount_val: float = 0.0
        if discount_f and discount_f.normalized_value:
            try:
                discount_val = float(discount_f.normalized_value)
            except ValueError:
                discount_val = 0.0

        if total_f and total_f.normalized_value and subtotal_val is not None:
            try:
                total_val = float(total_f.normalized_value)
                is_valid_total, total_err = validate_invoice_total(
                    subtotal_val, tax_amt_val, discount_val, total_val, self.tolerance
                )
                if not is_valid_total:
                    total_f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                    total_f.validation_message = total_err
            except ValueError:
                pass

    def _validate_onboarding(self, fields: List[ExtractedField], section_data: Dict[str, Any]):
        """Deterministic business validation for onboarding forms."""
        field_map = {f.field_name.lower(): f for f in fields}

        # 1. Full name is required
        name_f = field_map.get("full_name")
        if not name_f or name_f.field_value is None or str(name_f.field_value).strip() == "":
            if name_f:
                name_f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                name_f.validation_message = "Required full name is missing."
            else:
                fields.append(
                    ExtractedField(
                        field_name="full_name",
                        field_value=None,
                        normalized_value=None,
                        confidence=1.0,
                        source="validation",
                        source_text=None,
                        section_name="personal_information",
                        page_number=1,
                        validation_status=ValidationStatusEnum.NEEDS_REVIEW.value,
                        validation_message="Required full name is missing.",
                    )
                )

        # 2. At least one contact method (email or phone) is required
        email_f = field_map.get("email")
        phone_f = field_map.get("phone")
        has_email = email_f and email_f.field_value and str(email_f.field_value).strip()
        has_phone = phone_f and phone_f.field_value and str(phone_f.field_value).strip()
        if not has_email and not has_phone:
            if email_f:
                email_f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                email_f.validation_message = "At least one contact method (email or phone) is required."
            elif phone_f:
                phone_f.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                phone_f.validation_message = "At least one contact method (email or phone) is required."
            else:
                fields.append(
                    ExtractedField(
                        field_name="email",
                        field_value=None,
                        normalized_value=None,
                        confidence=1.0,
                        source="validation",
                        source_text=None,
                        section_name="contact_information",
                        page_number=1,
                        validation_status=ValidationStatusEnum.NEEDS_REVIEW.value,
                        validation_message="At least one contact method (email or phone) is required.",
                    )
                )
