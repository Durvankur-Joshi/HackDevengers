import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.pipeline.types import ExtractedField

# Known currency symbol mappings
CURRENCY_MAP = {
    "₹": "INR",
    "INR": "INR",
    "RS": "INR",
    "RS.": "INR",
    "$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "¥": "JPY",
    "JPY": "JPY",
}

# Date format candidates
DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y-%b-%d",
]


def normalize_date(val: Any) -> Tuple[Optional[str], bool, Optional[str]]:
    """
    Deterministically normalizes recognizable dates to YYYY-MM-DD.
    Returns (normalized_date_str, is_ambiguous_or_invalid, error_message).
    """
    if val is None:
        return None, False, None

    raw = str(val).strip()
    if not raw:
        return None, False, None

    # Clean leading/trailing quotes or punctuation
    raw = raw.strip("\"'.,;")

    # Direct match for ISO format YYYY-MM-DD
    if re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", raw):
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
            return parsed.strftime("%Y-%m-%d"), False, None
        except ValueError:
            return None, True, f"Invalid date value: {raw}"

    # Try standard date formats
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
            # Year sanity check (between 1900 and 2100)
            if 1900 <= parsed.year <= 2100:
                return parsed.strftime("%Y-%m-%d"), False, None
        except (ValueError, TypeError):
            continue

    # Try regex match for DD/MM/YYYY or MM/DD/YYYY
    match_slash = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", raw)
    if match_slash:
        p1, p2, yr = int(match_slash.group(1)), int(match_slash.group(2)), int(match_slash.group(3))
        if 1900 <= yr <= 2100:
            if p1 > 12 and 1 <= p2 <= 12:
                # Must be DD/MM/YYYY
                try:
                    dt = datetime(yr, p2, p1)
                    return dt.strftime("%Y-%m-%d"), False, None
                except ValueError:
                    pass
            elif p2 > 12 and 1 <= p1 <= 12:
                # Must be MM/DD/YYYY
                try:
                    dt = datetime(yr, p1, p2)
                    return dt.strftime("%Y-%m-%d"), False, None
                except ValueError:
                    pass
            elif 1 <= p1 <= 12 and 1 <= p2 <= 12:
                # Default to DD/MM/YYYY for standard Indian/UK invoice formats
                try:
                    dt = datetime(yr, p2, p1)
                    return dt.strftime("%Y-%m-%d"), False, None
                except ValueError:
                    pass

    return None, True, f"Ambiguous or unrecognized date format: '{raw}'"


def normalize_number(val: Any) -> Tuple[Optional[float], Optional[str]]:
    """
    Normalizes numeric values by removing presentation formatting (commas, spaces, currency symbols).
    Handles standard international and Indian numbering (e.g. ₹1,25,000 -> 125000.0).
    Returns (float_value, canonical_string).
    """
    if val is None:
        return None, None

    if isinstance(val, (int, float)):
        num = float(val)
        canon_str = f"{int(num)}" if num.is_integer() else f"{num:.2f}".rstrip("0").rstrip(".")
        return num, canon_str

    raw = str(val).strip()
    if not raw:
        return None, None

    # Remove currency symbols, percent signs, and word tokens
    cleaned = re.sub(r"[₹$€£¥%\s]", "", raw)
    cleaned = re.sub(r"(?i)^(inr|usd|eur|gbp|rs\.?)\s*", "", cleaned)

    # Check for empty after currency stripping
    if not cleaned:
        return None, None

    # Handle negative numbers with brackets e.g. (1,250.00) -> -1250.00
    is_negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        is_negative = True
        cleaned = cleaned[1:-1].strip()
    elif cleaned.startswith("-"):
        is_negative = True
        cleaned = cleaned[1:].strip()

    # Remove thousand/lakh separators (commas)
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            # European format: 1.250,50 -> 1250.50
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # Anglo/Indian format: 1,250.50 or 1,25,000.50 -> 1250.50
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) == 2 and not any(len(p) > 3 for p in parts):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")

    try:
        num = float(cleaned)
        if is_negative:
            num = -num
        canon_str = f"{int(num)}" if num.is_integer() else f"{num:.2f}".rstrip("0").rstrip(".")
        return num, canon_str
    except ValueError:
        return None, None


def normalize_currency(val: Any) -> Tuple[Optional[str], Optional[float]]:
    """
    Extracts canonical currency code and clean numeric value if present.
    Returns (currency_code, numeric_value).
    """
    if val is None:
        return None, None

    raw = str(val).strip()
    curr_found = None
    for symbol, code in CURRENCY_MAP.items():
        if symbol in raw.upper():
            curr_found = code
            break

    num, _ = normalize_number(raw)
    return curr_found, num


def normalize_email(val: Any) -> Tuple[Optional[str], bool]:
    """
    Normalizes email address: trims whitespace, lowercases, strips accidental quotes.
    Returns (normalized_email, is_present).
    """
    if val is None:
        return None, False

    raw = str(val).strip().strip("\"'<>")
    if not raw:
        return None, False

    cleaned = raw.lower().strip()
    return cleaned, True


def normalize_phone(val: Any) -> Tuple[Optional[str], bool]:
    """
    Normalizes phone numbers: trims whitespace, preserves country code (+) if present,
    strips spaces, hyphens, dots, parentheses.
    """
    if val is None:
        return None, False

    raw = str(val).strip().strip("\"'")
    if not raw:
        return None, False

    has_plus = raw.startswith("+")
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None, False

    norm = f"+{digits}" if has_plus else digits
    return norm, True


def normalize_text(val: Any) -> Optional[str]:
    """
    Normalizes ordinary text: trims leading/trailing whitespace, collapses internal whitespace.
    Preserves casing for proper nouns, names, addresses.
    """
    if val is None:
        return None

    raw = str(val).strip().strip("\"'")
    if not raw:
        return None

    return re.sub(r"\s+", " ", raw)


class FieldNormalizer:
    """
    Orchestrates conservative normalization across all extracted fields
    WITHOUT mutating the original field_value.
    """

    DATE_FIELDS = {
        "invoice_date",
        "due_date",
        "date_of_birth",
        "joining_date",
        "issue_date",
        "expiry_date",
        "date",
    }

    NUMERIC_FIELDS = {
        "subtotal",
        "tax_amount",
        "tax_rate",
        "discount",
        "total",
        "quantity",
        "unit_price",
        "line_total",
    }

    EMAIL_FIELDS = {
        "vendor_email",
        "customer_email",
        "email",
    }

    PHONE_FIELDS = {
        "vendor_phone",
        "customer_phone",
        "phone",
    }

    @classmethod
    def normalize_field(cls, field: ExtractedField) -> Tuple[Optional[str], bool, Optional[str]]:
        """
        Computes the canonical normalized_value for a field based on its field_name and raw field_value.
        Returns (normalized_value, is_ambiguous_or_malformed, error_message).
        """
        val = field.field_value
        fname = field.field_name.lower()

        if val is None:
            return None, False, None

        # 1. Date normalization
        if any(df in fname for df in cls.DATE_FIELDS):
            norm_date, is_err, msg = normalize_date(val)
            return norm_date, is_err, msg

        # 2. Numeric / Currency normalization
        if any(nf in fname for nf in cls.NUMERIC_FIELDS) or fname.endswith("_quantity") or fname.endswith("_unit_price") or fname.endswith("_price") or fname.endswith("_line_total") or fname.endswith("_total"):
            num_val, num_str = normalize_number(val)
            if num_val is not None:
                return num_str, False, None
            return None, True, f"Could not parse numeric value from '{val}'"

        # 3. Currency code field
        if fname == "currency":
            curr, _ = normalize_currency(val)
            if curr:
                return curr, False, None
            text_norm = normalize_text(val)
            return text_norm.upper() if text_norm else None, False, None

        # 4. Email normalization
        if any(ef in fname for ef in cls.EMAIL_FIELDS):
            email_norm, is_present = normalize_email(val)
            return email_norm, False, None

        # 5. Phone normalization
        if any(pf in fname for pf in cls.PHONE_FIELDS):
            phone_norm, is_present = normalize_phone(val)
            return phone_norm, False, None

        # 6. Default textual normalization
        text_norm = normalize_text(val)
        return text_norm, False, None
