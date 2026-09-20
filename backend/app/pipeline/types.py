from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class PreprocessedPage(BaseModel):
    page_number: int = Field(..., description="1-indexed sequential page number")
    image_path: str = Field(..., description="Path to the generated OCR-ready image")
    width: int = Field(..., description="Image width in pixels")
    height: int = Field(..., description="Image height in pixels")
    format: str = Field(default="png", description="Image encoding format")
    file_size_bytes: Optional[int] = Field(default=None, description="Image file size in bytes")


class PreprocessingResult(BaseModel):
    document_id: str = Field(..., description="Document UUID")
    original_filename: str = Field(..., description="Original uploaded filename")
    mime_type: str = Field(..., description="Detected MIME type")
    page_count: int = Field(..., description="Total preprocessed pages")
    pages: List[PreprocessedPage] = Field(default_factory=list, description="Ordered OCR-ready pages")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metadata and timing")
    status: str = Field(default="preprocessed", description="Document status after preprocessing")


class BoundingBox(BaseModel):
    x: int = Field(..., description="Top-left X coordinate in pixels")
    y: int = Field(..., description="Top-left Y coordinate in pixels")
    width: int = Field(..., description="Box width in pixels")
    height: int = Field(..., description="Box height in pixels")


class OCRBlock(BaseModel):
    block_index: int = Field(..., description="0-indexed sequence of text block in reading order")
    text: str = Field(..., description="Extracted textual content")
    confidence: Optional[float] = Field(default=None, description="OCR confidence score (0-100)")
    bbox: BoundingBox = Field(..., description="Pixel bounding box in preprocessed image")
    page_number: int = Field(..., description="1-indexed page number")


class OCRPageResult(BaseModel):
    page_number: int = Field(..., description="1-indexed page number")
    width: int = Field(..., description="Page width in pixels")
    height: int = Field(..., description="Page height in pixels")
    text: str = Field(default="", description="Consolidated page text")
    blocks: List[OCRBlock] = Field(default_factory=list, description="Ordered text blocks on this page")


class OCRMetadata(BaseModel):
    block_count: int = Field(..., description="Total extracted text blocks across all pages")
    average_confidence: Optional[float] = Field(default=None, description="Average OCR confidence across valid blocks")
    processing_duration_ms: Optional[int] = Field(default=None, description="Total execution duration in milliseconds")
    ocr_engine: str = Field(default="tesseract", description="Identifier of the OCR engine used")


class OCRDocumentResult(BaseModel):
    document_id: str = Field(..., description="Document UUID")
    page_count: int = Field(..., description="Total pages processed")
    full_text: str = Field(..., description="Full multi-page document text with page delimiters")
    pages: List[OCRPageResult] = Field(default_factory=list, description="Sequential OCR page results")
    metadata: OCRMetadata = Field(..., description="Document-level OCR metadata and metrics")


class DocumentType(str, Enum):
    INVOICE = "invoice"
    ONBOARDING_FORM = "onboarding_form"
    UNKNOWN = "unknown"


class GeminiClassificationOutput(BaseModel):
    document_type: DocumentType = Field(
        ...,
        description="Classified document archetype: 'invoice', 'onboarding_form', or 'unknown'"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Classification confidence score between 0.0 and 1.0"
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Concise reasons justifying the classification"
    )


class DocumentClassificationResult(BaseModel):
    document_id: str = Field(..., description="Document UUID")
    document_type: DocumentType = Field(..., description="Assigned document classification")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence (0.0 - 1.0)")
    evidence: List[str] = Field(default_factory=list, description="Textual evidence justifying classification")
    ocr_average_confidence: Optional[float] = Field(default=None, description="Average OCR quality confidence")
    classified_at: str = Field(..., description="ISO 8601 classification timestamp")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution and threshold metadata")


# ==============================================================================
# Phase 7 — Section Detection Types & Schemas
# ==============================================================================

class InvoiceSectionType(str, Enum):
    VENDOR_INFORMATION = "vendor_information"
    CUSTOMER_INFORMATION = "customer_information"
    INVOICE_METADATA = "invoice_metadata"
    LINE_ITEMS = "line_items"
    PAYMENT_INFORMATION = "payment_information"
    TAX_INFORMATION = "tax_information"
    NOTES = "notes"
    UNKNOWN = "unknown"


class OnboardingSectionType(str, Enum):
    PERSONAL_INFORMATION = "personal_information"
    CONTACT_INFORMATION = "contact_information"
    EMPLOYMENT_INFORMATION = "employment_information"
    EMERGENCY_CONTACT = "emergency_contact"
    IDENTITY_DOCUMENTS = "identity_documents"
    BANK_DETAILS = "bank_details"
    AGREEMENTS = "agreements"
    NOTES = "notes"
    UNKNOWN = "unknown"


class GeminiRawSection(BaseModel):
    """Raw section item emitted by Gemini structured output."""
    section_name: str = Field(..., description="Detected section archetype identifier")
    page_number: int = Field(default=1, description="1-indexed page number where the section is located")
    text: str = Field(..., description="Exact raw text content belonging to this section")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Section detection confidence between 0.0 and 1.0")
    block_ids: List[int] = Field(default_factory=list, description="OCR block indices belonging to this section")


class GeminiSectionDetectionOutput(BaseModel):
    """Schema for Gemini section detection structured JSON response."""
    sections: List[GeminiRawSection] = Field(
        default_factory=list,
        description="Logical document sections identified from OCR blocks and text"
    )


class DocumentSection(BaseModel):
    """Typed document section representation for storage, downstream extraction, and API response."""
    section_id: str = Field(..., description="Section UUID")
    document_id: str = Field(..., description="Parent document UUID")
    section_name: str = Field(..., description="Normalized section name")
    page_number: int = Field(default=1, description="1-indexed page number")
    text: str = Field(..., description="Extracted raw text content of the section")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Section detection confidence (0.0 - 1.0)")
    block_ids: List[int] = Field(default_factory=list, description="OCR block indices belonging to this section")
    bbox: Optional[BoundingBox] = Field(default=None, description="Enclosing bounding box of the section")


class DocumentSectionResult(BaseModel):
    """Final output of Phase 7 section detection stage."""
    document_id: str = Field(..., description="Document UUID")
    document_type: str = Field(..., description="Document type: invoice, onboarding_form, or unknown")
    sections: List[DocumentSection] = Field(default_factory=list, description="List of detected document sections")


# ==============================================================================
# Phase 8 — Targeted Structured AI Extraction Schemas
# ==============================================================================

class ExtractedFieldProvenance(BaseModel):
    """Provenance tracking for an individual extracted string field value."""
    value: Optional[str] = Field(default=None, description="Extracted string value or null if not present in text")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0 from model, or null")
    source_text: Optional[str] = Field(default=None, description="Exact short excerpt from section text where this was found")


class ExtractedNumberProvenance(BaseModel):
    """Provenance tracking for a numeric extracted field."""
    value: Optional[float] = Field(default=None, description="Extracted numeric value or null if not present")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0 from model, or null")
    source_text: Optional[str] = Field(default=None, description="Exact short excerpt from section text where this was found")


class ExtractedBoolProvenance(BaseModel):
    """Provenance tracking for a boolean extracted field."""
    value: Optional[bool] = Field(default=None, description="Extracted boolean value or null if not present")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0 from model, or null")
    source_text: Optional[str] = Field(default=None, description="Exact short excerpt from section text where this was found")


# --- Invoice Section Schemas ---

class VendorInfoExtraction(BaseModel):
    vendor_name: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    vendor_address: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    vendor_email: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    vendor_phone: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    vendor_tax_id: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class CustomerInfoExtraction(BaseModel):
    customer_name: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    customer_address: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    customer_email: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    customer_phone: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    customer_tax_id: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class InvoiceMetadataExtraction(BaseModel):
    invoice_number: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    invoice_date: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    due_date: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    currency: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    purchase_order_number: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class LineItemExtraction(BaseModel):
    description: Optional[str] = Field(default=None, description="Description of product or service")
    quantity: Optional[float] = Field(default=None, description="Item quantity")
    unit_price: Optional[float] = Field(default=None, description="Price per unit")
    tax_rate: Optional[float] = Field(default=None, description="Tax rate percentage or decimal")
    line_total: Optional[float] = Field(default=None, description="Total price for this line item")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Extraction confidence")
    source_text: Optional[str] = Field(default=None, description="Exact text line from invoice")


class LineItemsExtraction(BaseModel):
    items: List[LineItemExtraction] = Field(default_factory=list, description="List of line items")


class TaxInfoExtraction(BaseModel):
    subtotal: Optional[ExtractedNumberProvenance] = Field(default_factory=ExtractedNumberProvenance)
    tax_amount: Optional[ExtractedNumberProvenance] = Field(default_factory=ExtractedNumberProvenance)
    tax_rate: Optional[ExtractedNumberProvenance] = Field(default_factory=ExtractedNumberProvenance)
    discount: Optional[ExtractedNumberProvenance] = Field(default_factory=ExtractedNumberProvenance)
    total: Optional[ExtractedNumberProvenance] = Field(default_factory=ExtractedNumberProvenance)


class PaymentInfoExtraction(BaseModel):
    payment_method: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    bank_name: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    account_number: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    ifsc: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    payment_reference: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class NotesExtraction(BaseModel):
    notes: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


# --- Onboarding Form Section Schemas ---

class PersonalInfoExtraction(BaseModel):
    full_name: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    date_of_birth: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    gender: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    nationality: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class ContactInfoExtraction(BaseModel):
    email: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    phone: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    address: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    city: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    state: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    postal_code: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class EmploymentInfoExtraction(BaseModel):
    employee_id: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    designation: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    department: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    joining_date: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    employment_type: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class EmergencyContactExtraction(BaseModel):
    name: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    relationship: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    phone: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    email: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class IdentityDocItem(BaseModel):
    document_type: Optional[str] = Field(default=None, description="e.g. Passport, Driver License, SSN, PAN")
    document_number: Optional[str] = Field(default=None, description="Document identification number")
    issue_date: Optional[str] = Field(default=None, description="Document issue date")
    expiry_date: Optional[str] = Field(default=None, description="Document expiration date")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_text: Optional[str] = Field(default=None)


class IdentityDocsExtraction(BaseModel):
    documents: List[IdentityDocItem] = Field(default_factory=list)


class BankDetailsExtraction(BaseModel):
    account_holder_name: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    bank_name: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    account_number: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)
    ifsc: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


class AgreementItem(BaseModel):
    agreement_type: Optional[str] = Field(default=None, description="e.g. Background check, Terms of employment, NDA")
    accepted: Optional[bool] = Field(default=None, description="true if explicitly agreed/signed, false or null if not")
    date: Optional[str] = Field(default=None, description="Date signed/agreed")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_text: Optional[str] = Field(default=None)


class AgreementsExtraction(BaseModel):
    agreements: List[AgreementItem] = Field(default_factory=list)


class OnboardingNotesExtraction(BaseModel):
    notes: Optional[ExtractedFieldProvenance] = Field(default_factory=ExtractedFieldProvenance)


# --- Provenance Record & Final Extraction Result ---

class ExtractedField(BaseModel):
    """Standardized provenance record for an individual extracted field."""
    id: Optional[str] = Field(default=None, description="Unique field UUID")
    section_id: Optional[str] = Field(default=None, description="UUID of the parent document_sections row")
    field_name: str = Field(..., description="Canonical field identifier")
    field_value: Optional[Any] = Field(default=None, description="Typed or string value, null if not present")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Extraction confidence score (0.0 - 1.0)")
    source: str = Field(default="gemini", description="Extraction engine source")
    source_text: Optional[str] = Field(default=None, description="Targeted source text excerpt where value was located")
    section_name: str = Field(..., description="Section from which field was extracted")
    page_number: int = Field(default=1, description="Page number where field was located")
    normalized_value: Optional[str] = Field(default=None, description="Deterministic canonical normalized representation")
    validation_status: Optional[str] = Field(default=None, description="Validation status: 'valid', 'needs_review', or 'conflict'")
    validation_message: Optional[str] = Field(default=None, description="Explanation for non-valid status")
    normalized_at: Optional[str] = Field(default=None, description="ISO timestamp of normalization/validation")
    ocr_value: Optional[Any] = Field(default=None, description="Original OCR-extracted raw value for provenance")
    ocr_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Original OCR confidence score")
    vision_value: Optional[str] = Field(default=None, description="Recovered value from Gemini Vision fallback")
    vision_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidence score from Gemini Vision")
    vision_source_text: Optional[str] = Field(default=None, description="Contextual text read in visual crop")
    fallback_attempted: bool = Field(default=False, description="Whether vision fallback was attempted for this field")
    fallback_reason: Optional[str] = Field(default=None, description="Trigger reason for vision fallback")


class DocumentExtractionResult(BaseModel):
    """Final result of Phase 8 targeted structured AI extraction stage."""
    document_id: str = Field(..., description="Document UUID")
    document_type: str = Field(..., description="Document type: invoice, onboarding_form, or unknown")
    status: str = Field(default="extracted", description="Extraction status: 'extracted' or 'skipped'")
    reason: Optional[str] = Field(default=None, description="Explanation if extraction was skipped")
    fields: List[ExtractedField] = Field(default_factory=list, description="Flat list of all extracted fields with provenance")
    section_data: Dict[str, Any] = Field(default_factory=dict, description="Structured fields grouped by section")
    extracted_at: str = Field(..., description="ISO 8601 timestamp of extraction")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata including section count and model used")


# --- Phase 9: Normalization & Deterministic Validation Models ---

class ValidationStatusEnum(str, Enum):
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    CONFLICT = "conflict"


class DocumentValidationSummary(BaseModel):
    """Validation count metrics without percentages or arbitrary scoring."""
    total_fields: int = Field(default=0, description="Total number of evaluated fields")
    valid_count: int = Field(default=0, description="Fields meeting all format and deterministic rules")
    needs_review_count: int = Field(default=0, description="Fields requiring human review or calculation fixes")
    conflict_count: int = Field(default=0, description="Fields with conflicting duplicate extractions")


class DocumentValidationResult(BaseModel):
    """Final output of Phase 9 Deterministic Normalization and Validation stage."""
    document_id: str = Field(..., description="Document UUID")
    document_type: str = Field(..., description="Document type: invoice, onboarding_form, or unknown")
    document_status: str = Field(..., description="Document status: 'completed' or 'needs_review'")
    summary: DocumentValidationSummary = Field(default_factory=DocumentValidationSummary)
    fields: List[ExtractedField] = Field(default_factory=list, description="Fields with normalized values and validation statuses")
    validation_issues: List[Dict[str, Any]] = Field(default_factory=list, description="List of non-valid issues with field and message")
    validated_at: str = Field(..., description="ISO 8601 timestamp of validation execution")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata including tolerance and rules evaluated")


# --- Phase 10: Low-Confidence & Handwriting Vision Fallback Models ---

class GeminiVisionRecoveryOutput(BaseModel):
    """Structured response schema returned by Gemini Vision for a targeted image crop."""
    field_name: str = Field(..., description="Canonical field identifier requested")
    value: Optional[str] = Field(default=None, description="Extracted visible field value, or null if unreadable/ambiguous")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidence in the visual reading (0.0 to 1.0)")
    source_text: Optional[str] = Field(default=None, description="Surrounding visible text context in crop")
    reason: Optional[str] = Field(default=None, description="Visual observation or justification")


class VisionFallbackFieldResult(BaseModel):
    """Result of an individual field vision fallback evaluation."""
    field_name: str = Field(..., description="Canonical field identifier")
    action_taken: str = Field(..., description="Outcome: 'recovered', 'agreed', 'conflict', 'unreadable', or 'skipped'")
    ocr_value: Optional[Any] = Field(default=None, description="Previous OCR-extracted value")
    ocr_confidence: Optional[float] = Field(default=None, description="Previous OCR confidence")
    vision_value: Optional[str] = Field(default=None, description="Value returned by Gemini Vision")
    vision_confidence: Optional[float] = Field(default=None, description="Confidence returned by Gemini Vision")
    reason: Optional[str] = Field(default=None, description="Explanation of action taken")
    crop_box: Optional[BoundingBox] = Field(default=None, description="Pixel bounding box cropped from preprocessed page")
    page_number: int = Field(default=1, description="Page number cropped")


class DocumentVisionFallbackResult(BaseModel):
    """Final output of Phase 10 Targeted Vision Fallback stage."""
    document_id: str = Field(..., description="Document UUID")
    document_type: str = Field(..., description="Document type: invoice, onboarding_form, or unknown")
    status: str = Field(default="completed", description="'completed', 'skipped', or 'no_candidates'")
    candidates_identified: int = Field(default=0, description="Number of low-confidence or suspicious fields identified")
    fields_recovered: int = Field(default=0, description="Number of fields successfully corrected/recovered by vision")
    conflicts_detected: int = Field(default=0, description="Number of conflicts between OCR and vision")
    fallback_fields: List[VisionFallbackFieldResult] = Field(default_factory=list, description="Per-field fallback outcomes")
    fields: List[ExtractedField] = Field(default_factory=list, description="Updated extracted fields with vision provenance")
    updated_validation: Optional[DocumentValidationResult] = Field(default=None, description="Re-validated document results")
    processed_at: str = Field(..., description="ISO 8601 timestamp of fallback execution")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metadata and thresholds")
