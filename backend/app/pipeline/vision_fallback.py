import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

from app.core.config import settings
from app.pipeline.normalizer import FieldNormalizer
from app.pipeline.types import (
    BoundingBox,
    DocumentValidationResult,
    DocumentVisionFallbackResult,
    ExtractedField,
    GeminiVisionRecoveryOutput,
    ValidationStatusEnum,
    VisionFallbackFieldResult,
)
from app.pipeline.validator import DocumentValidator
from app.services.gemini import gemini_service, GeminiService

logger = logging.getLogger(__name__)


def values_agree(val1: Any, val2: Any) -> bool:
    """
    Deterministic string & numeric equivalence check across OCR and Vision extractions.
    Ignores currency symbols, whitespace, commas, and formatting noise.
    """
    if val1 is None or val2 is None:
        return False

    s1 = str(val1).strip()
    s2 = str(val2).strip()
    if not s1 or not s2:
        return False

    if s1.lower() == s2.lower():
        return True

    def clean_str(s: str) -> str:
        return re.sub(r"[₹$€£¥,\s\-_/.:;\"']", "", s).lower()

    c1 = clean_str(s1)
    c2 = clean_str(s2)
    if c1 and c1 == c2:
        return True

    # Numeric comparison if both contain digits
    try:
        digits_1 = re.sub(r"[^\d.]", "", s1)
        digits_2 = re.sub(r"[^\d.]", "", s2)
        if digits_1 and digits_2:
            f1 = float(digits_1)
            f2 = float(digits_2)
            if abs(f1 - f2) <= settings.INVOICE_ROUNDING_TOLERANCE:
                return True
    except (ValueError, TypeError):
        pass

    return False


class VisionFallbackManager:
    """
    Surgical, targeted recovery manager using Gemini Vision for low-confidence or
    corrupted OCR extractions. Never passes full document pages to Vision AI.
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

    def identify_candidates(self, fields: List[ExtractedField]) -> List[Tuple[ExtractedField, str]]:
        """
        Identifies qualifying low-confidence, empty, or format-corrupted fields
        for targeted visual inspection.
        Filters out fields with high confidence arithmetic-only issues or already attempted.
        """
        candidates: List[Tuple[ExtractedField, str]] = []
        conf_threshold = settings.VISION_FALLBACK_CONFIDENCE_THRESHOLD

        for field in fields:
            # 1. Skip if already attempted
            if field.fallback_attempted:
                continue

            # 2. Skip non-visual synthetic fields (like notes sections if empty, or agreement flags)
            fname = field.field_name.lower()
            if fname.startswith("agreement_") or fname in ("notes",):
                continue

            # 3. Check for low confidence (< threshold)
            if field.confidence is not None and field.confidence < conf_threshold:
                reason = f"Low OCR confidence ({field.confidence:.2f} < {conf_threshold:.2f})"
                candidates.append((field, reason))
                continue

            # 4. Check for empty/missing value
            if field.field_value is None or str(field.field_value).strip() == "":
                # If validation flagged it as missing or confidence was low/missing
                if field.validation_status == ValidationStatusEnum.NEEDS_REVIEW.value:
                    reason = f"Missing value flagged during validation: {field.validation_message or 'Required field empty'}"
                    candidates.append((field, reason))
                    continue

            # 5. Check validation status for format or OCR character corruption
            if field.validation_status == ValidationStatusEnum.NEEDS_REVIEW.value:
                msg = (field.validation_message or "").lower()
                # Skip arithmetic discrepancies when confidence is high (vision cannot fix pure math)
                if "discrepancy" in msg or "does not match calculated" in msg or "earlier than invoice date" in msg:
                    continue

                if "format is invalid" in msg or "must contain between" in msg or "could not parse" in msg or "invalid" in msg:
                    reason = f"OCR format/corruption issue: {field.validation_message}"
                    candidates.append((field, reason))
                    continue

        return candidates

    def locate_crop_box(
        self,
        document_id: str,
        field: ExtractedField,
        ocr_data: Optional[Dict[str, Any]] = None,
        sections_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[BoundingBox]:
        """
        Locates the targeted pixel bounding box for a field using:
        1. Exact or fuzzy match on source_text / field_value in OCRBlocks on the specified page.
        2. Fallback to enclosing section bounding box.
        3. Fallback to union bounding box of section's block_ids.
        """
        doc_dir = self.base_dir / document_id

        # Load OCR data if not provided
        if ocr_data is None:
            ocr_path = doc_dir / "ocr_result.json"
            if not ocr_path.exists():
                ocr_path = doc_dir / "ocr.json"
            if ocr_path.exists():
                try:
                    with open(ocr_path, "r", encoding="utf-8") as f:
                        ocr_data = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to read OCR json for doc {document_id}: {e}")

        # Load sections data if not provided
        if sections_data is None:
            sec_path = doc_dir / "sections.json"
            if sec_path.exists():
                try:
                    with open(sec_path, "r", encoding="utf-8") as f:
                        sections_data = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to read sections.json for doc {document_id}: {e}")

        page_num = field.page_number or 1

        # Step 1: Match blocks from OCR by source_text or field_value
        if ocr_data and "pages" in ocr_data:
            target_page = None
            for p in ocr_data["pages"]:
                if p.get("page_number") == page_num:
                    target_page = p
                    break

            if target_page and "blocks" in target_page:
                matching_blocks = []
                st = (field.source_text or "").strip().lower()
                val_str = str(field.field_value or "").strip().lower()

                for b in target_page["blocks"]:
                    b_text = (b.get("text") or "").strip().lower()
                    if not b_text:
                        continue

                    # Exact or substring match with source_text
                    if st and (st in b_text or b_text in st):
                        matching_blocks.append(b)
                    elif val_str and len(val_str) >= 3 and val_str in b_text:
                        matching_blocks.append(b)

                if matching_blocks:
                    # Union bounding box across matching blocks
                    min_x = min(b["bbox"]["x"] for b in matching_blocks)
                    min_y = min(b["bbox"]["y"] for b in matching_blocks)
                    max_x = max(b["bbox"]["x"] + b["bbox"]["width"] for b in matching_blocks)
                    max_y = max(b["bbox"]["y"] + b["bbox"]["height"] for b in matching_blocks)
                    return BoundingBox(
                        x=int(min_x),
                        y=int(min_y),
                        width=int(max_x - min_x),
                        height=int(max_y - min_y),
                    )

        # Step 2: Fallback to section bounding box
        if sections_data and "sections" in sections_data:
            target_sec_name = field.section_name.lower()
            for s in sections_data["sections"]:
                if s.get("section_name", "").lower() == target_sec_name and s.get("page_number", 1) == page_num:
                    s_bbox = s.get("bbox")
                    if s_bbox and isinstance(s_bbox, dict) and s_bbox.get("width", 0) > 0 and s_bbox.get("height", 0) > 0:
                        return BoundingBox(
                            x=int(s_bbox["x"]),
                            y=int(s_bbox["y"]),
                            width=int(s_bbox["width"]),
                            height=int(s_bbox["height"]),
                        )

                    # Step 3: Union block_ids if present in section
                    block_ids = s.get("block_ids", [])
                    if block_ids and ocr_data and "pages" in ocr_data:
                        target_page = next((p for p in ocr_data["pages"] if p.get("page_number") == page_num), None)
                        if target_page and "blocks" in target_page:
                            sec_blocks = [
                                b for b in target_page["blocks"]
                                if b.get("block_index") in block_ids and "bbox" in b
                            ]
                            if sec_blocks:
                                min_x = min(b["bbox"]["x"] for b in sec_blocks)
                                min_y = min(b["bbox"]["y"] for b in sec_blocks)
                                max_x = max(b["bbox"]["x"] + b["bbox"]["width"] for b in sec_blocks)
                                max_y = max(b["bbox"]["y"] + b["bbox"]["height"] for b in sec_blocks)
                                return BoundingBox(
                                    x=int(min_x),
                                    y=int(min_y),
                                    width=int(max_x - min_x),
                                    height=int(max_y - min_y),
                                )

        return None

    def crop_image(
        self,
        document_id: str,
        page_number: int,
        bbox: BoundingBox,
        padding: Optional[int] = None,
    ) -> Optional[Tuple[Image.Image, BoundingBox]]:
        """
        Safely crops localized region from preprocessed page image with boundary clamping and context padding.
        Returns (PIL.Image, clamped_bounding_box) or None.
        """
        pad = padding if padding is not None else settings.VISION_CROP_PADDING
        doc_dir = self.base_dir / document_id
        page_file = doc_dir / f"page_{page_number:03d}.png"

        if not page_file.exists():
            # Check fallback pattern
            candidates = list(doc_dir.glob("page_*.png"))
            if candidates:
                page_file = candidates[0]
            else:
                logger.error(f"Page image file not found for doc {document_id}, page {page_number}")
                return None

        try:
            with Image.open(page_file) as img:
                img_w, img_h = img.size

                x_min = max(0, int(bbox.x - pad))
                y_min = max(0, int(bbox.y - pad))
                x_max = min(img_w, int(bbox.x + bbox.width + pad))
                y_max = min(img_h, int(bbox.y + bbox.height + pad))

                # Sanity check valid box
                if x_max <= x_min or y_max <= y_min:
                    logger.warning(f"Invalid crop dimensions for bbox: {bbox}")
                    return None

                clamped_bbox = BoundingBox(
                    x=x_min,
                    y=y_min,
                    width=x_max - x_min,
                    height=y_max - y_min,
                )

                cropped = img.crop((x_min, y_min, x_max, y_max))
                # Return a copy so underlying file handle closes cleanly
                return cropped.copy(), clamped_bbox

        except Exception as e:
            logger.error(f"Error cropping page image {page_file}: {e}")
            return None

    def build_multimodal_prompt(self, field: ExtractedField) -> str:
        """
        Builds strict, zero-hallucination multimodal prompt for Gemini Vision.
        """
        return f"""You are an expert handwriting and degraded document text recovery AI.
You are given a tightly cropped image region from a document page.
Your task is to visually inspect this image crop and read the field '{field.field_name}'.

TARGET FIELD: {field.field_name}
DOCUMENT SECTION: {field.section_name}
PREVIOUS OCR READ: {field.field_value if field.field_value is not None else 'None (empty or unreadable)'}
SURROUNDING OCR CONTEXT: {field.source_text if field.source_text else 'N/A'}

CRITICAL ANTI-HALLUCINATION INSTRUCTIONS:
1. ONLY read characters that are clearly and unambiguously visible in this image crop.
2. If the text or handwriting is illegible, smudged, cut off, or absent, set "value" to null.
3. NEVER guess, invent, autocomplete, or hallucinate missing letters, names, numbers, or words.
4. If the previous OCR read contains obvious OCR character confusion (e.g. 'O' vs '0', 'l' vs '1', 'S' vs '5', or broken characters), carefully inspect the image to output the correct visual character.
5. Provide your confidence (0.0 to 1.0) strictly reflecting how clearly legible the visual text is.
6. Provide "source_text" with any immediately surrounding visual text or labels visible in the crop.
7. Provide a concise "reason" explaining what you observed visually.
"""

    def evaluate_recovery(
        self,
        field: ExtractedField,
        vision_out: GeminiVisionRecoveryOutput,
        candidate_reason: str,
        crop_box: Optional[BoundingBox] = None,
    ) -> VisionFallbackFieldResult:
        """
        Evaluates Gemini Vision output against original OCR value and updates field provenance.
        Outcomes: 'recovered', 'agreed', 'conflict', 'unreadable', or 'skipped'.
        """
        ocr_val = field.field_value
        ocr_conf = field.confidence
        v_val = vision_out.value
        v_conf = vision_out.confidence

        # Preserve original OCR provenance
        if field.ocr_value is None:
            field.ocr_value = ocr_val
        if field.ocr_confidence is None:
            field.ocr_confidence = ocr_conf

        # Record vision fallback attempt
        field.fallback_attempted = True
        field.fallback_reason = candidate_reason
        field.vision_value = v_val
        field.vision_confidence = v_conf
        field.vision_source_text = vision_out.source_text

        # 1. Unreadable outcome
        if v_val is None or str(v_val).strip() == "":
            field.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
            field.validation_message = f"Handwriting or character unreadable in visual crop ({vision_out.reason or 'Illegible'})."
            return VisionFallbackFieldResult(
                field_name=field.field_name,
                action_taken="unreadable",
                ocr_value=ocr_val,
                ocr_confidence=ocr_conf,
                vision_value=None,
                vision_confidence=v_conf,
                reason=vision_out.reason or "Text unreadable in visual crop",
                crop_box=crop_box,
                page_number=field.page_number,
            )

        # 2. Agreement outcome
        if values_agree(ocr_val, v_val):
            field.confidence = max(field.confidence or 0.0, v_conf or 0.85)
            field.source = "ocr+vision"
            return VisionFallbackFieldResult(
                field_name=field.field_name,
                action_taken="agreed",
                ocr_value=ocr_val,
                ocr_confidence=ocr_conf,
                vision_value=v_val,
                vision_confidence=v_conf,
                reason=f"Vision confirmed OCR reading: '{v_val}'",
                crop_box=crop_box,
                page_number=field.page_number,
            )

        # 3. Recovery outcome from empty OCR
        if ocr_val is None or str(ocr_val).strip() == "":
            field.field_value = v_val
            field.confidence = v_conf or 0.85
            field.source = "vision_fallback"
            return VisionFallbackFieldResult(
                field_name=field.field_name,
                action_taken="recovered",
                ocr_value=ocr_val,
                ocr_confidence=ocr_conf,
                vision_value=v_val,
                vision_confidence=v_conf,
                reason=f"Recovered missing field from visual crop: '{v_val}'",
                crop_box=crop_box,
                page_number=field.page_number,
            )

        # 4. Values differ
        # If OCR had low confidence or invalid format, and Vision has reasonable confidence -> Recover/Correct
        is_ocr_low = (ocr_conf is None or ocr_conf < settings.VISION_FALLBACK_CONFIDENCE_THRESHOLD)
        is_vision_confident = (v_conf is not None and v_conf >= 0.70)

        if is_ocr_low and is_vision_confident:
            field.field_value = v_val
            field.confidence = v_conf
            field.source = "vision_fallback"
            return VisionFallbackFieldResult(
                field_name=field.field_name,
                action_taken="recovered",
                ocr_value=ocr_val,
                ocr_confidence=ocr_conf,
                vision_value=v_val,
                vision_confidence=v_conf,
                reason=f"Corrected low-confidence OCR ('{ocr_val}') to visual read '{v_val}'",
                crop_box=crop_box,
                page_number=field.page_number,
            )

        # Both have high confidence or cannot reconcile -> Conflict
        field.validation_status = ValidationStatusEnum.CONFLICT.value
        field.validation_message = f"Conflict between OCR ('{ocr_val}') and Vision ('{v_val}')."
        return VisionFallbackFieldResult(
            field_name=field.field_name,
            action_taken="conflict",
            ocr_value=ocr_val,
            ocr_confidence=ocr_conf,
            vision_value=v_val,
            vision_confidence=v_conf,
            reason=f"Conflict: OCR read '{ocr_val}' (conf {ocr_conf}) vs Vision '{v_val}' (conf {v_conf})",
            crop_box=crop_box,
            page_number=field.page_number,
        )

    def execute_fallback(
        self,
        document_id: str,
        document_type: Optional[str] = None,
        fields: Optional[List[ExtractedField]] = None,
        section_data: Optional[Dict[str, Any]] = None,
    ) -> DocumentVisionFallbackResult:
        """
        Main entry point for Phase 10 Low-Confidence & Handwriting Vision Fallback.
        1. Identifies qualifying candidate fields.
        2. Crops bounding boxes from preprocessed page images.
        3. Executes Gemini Vision multimodal recovery.
        4. Re-normalizes updated fields via FieldNormalizer.
        5. Re-validates document via DocumentValidator.
        6. Persists vision_fallback.json and updates validation.json.
        """
        doc_dir = self.base_dir / document_id
        now_iso = datetime.utcnow().isoformat()

        # Load existing validation / extraction if fields not provided
        if fields is None:
            val_file = doc_dir / "validation.json"
            ext_file = doc_dir / "extraction.json"
            if val_file.exists():
                try:
                    with open(val_file, "r", encoding="utf-8") as f:
                        vdata = json.load(f)
                    fields = [ExtractedField.model_validate(f_item) for f_item in vdata.get("fields", [])]
                    if not document_type:
                        document_type = vdata.get("document_type")
                except Exception as e:
                    logger.warning(f"Could not load validation.json for doc {document_id}: {e}")

            if fields is None and ext_file.exists():
                try:
                    with open(ext_file, "r", encoding="utf-8") as f:
                        edata = json.load(f)
                    fields = [ExtractedField.model_validate(f_item) for f_item in edata.get("fields", [])]
                    if not document_type:
                        document_type = edata.get("document_type")
                    if not section_data:
                        section_data = edata.get("section_data", {})
                except Exception as e:
                    logger.warning(f"Could not load extraction.json for doc {document_id}: {e}")

        fields = fields or []
        doc_type = document_type or "unknown"

        # If no fields at all
        if not fields:
            res = DocumentVisionFallbackResult(
                document_id=document_id,
                document_type=doc_type,
                status="skipped",
                candidates_identified=0,
                fields_recovered=0,
                conflicts_detected=0,
                fallback_fields=[],
                fields=[],
                updated_validation=None,
                processed_at=now_iso,
                metadata={"message": "No extracted fields available for fallback evaluation."},
            )
            return res

        # 1. Identify Candidates
        candidates = self.identify_candidates(fields)
        if not candidates:
            logger.info(f"No vision fallback candidates identified for document {document_id}.")
            res = DocumentVisionFallbackResult(
                document_id=document_id,
                document_type=doc_type,
                status="no_candidates",
                candidates_identified=0,
                fields_recovered=0,
                conflicts_detected=0,
                fallback_fields=[],
                fields=fields,
                updated_validation=None,
                processed_at=now_iso,
                metadata={"message": "All fields have high confidence or valid deterministic state."},
            )
            self._save_results(doc_dir, res)
            return res

        logger.info(f"Identified {len(candidates)} candidate field(s) for vision fallback in doc {document_id}.")

        # Load OCR & Section data once for cropping
        ocr_path = doc_dir / "ocr_result.json"
        if not ocr_path.exists():
            ocr_path = doc_dir / "ocr.json"
        ocr_data = None
        if ocr_path.exists():
            try:
                with open(ocr_path, "r", encoding="utf-8") as f:
                    ocr_data = json.load(f)
            except Exception as e:
                logger.warning(f"Error loading OCR data: {e}")

        sec_path = doc_dir / "sections.json"
        sections_data = None
        if sec_path.exists():
            try:
                with open(sec_path, "r", encoding="utf-8") as f:
                    sections_data = json.load(f)
            except Exception as e:
                logger.warning(f"Error loading sections.json: {e}")

        fallback_results: List[VisionFallbackFieldResult] = []
        recovered_count = 0
        conflict_count = 0

        # 2. Process each candidate
        for field, candidate_reason in candidates:
            # Locate bounding box
            bbox = self.locate_crop_box(document_id, field, ocr_data, sections_data)
            if not bbox:
                logger.warning(f"Could not locate bounding box for field '{field.field_name}'. Skipping vision.")
                field.fallback_attempted = True
                field.fallback_reason = f"No bounding box located ({candidate_reason})"
                fallback_results.append(
                    VisionFallbackFieldResult(
                        field_name=field.field_name,
                        action_taken="skipped",
                        ocr_value=field.field_value,
                        ocr_confidence=field.confidence,
                        reason="Could not determine bounding box to crop safely",
                        crop_box=None,
                        page_number=field.page_number,
                    )
                )
                continue

            # Safely crop image region
            crop_result = self.crop_image(document_id, field.page_number, bbox)
            if not crop_result:
                logger.warning(f"Failed to crop image for field '{field.field_name}'. Skipping vision.")
                field.fallback_attempted = True
                field.fallback_reason = f"Image crop failed ({candidate_reason})"
                fallback_results.append(
                    VisionFallbackFieldResult(
                        field_name=field.field_name,
                        action_taken="skipped",
                        ocr_value=field.field_value,
                        ocr_confidence=field.confidence,
                        reason="Failed to crop image region from page",
                        crop_box=bbox,
                        page_number=field.page_number,
                    )
                )
                continue

            cropped_img, clamped_bbox = crop_result

            # 3. Call Gemini Vision
            prompt = self.build_multimodal_prompt(field)
            try:
                vision_out = self.gemini.recover_field_vision(
                    image=cropped_img,
                    prompt=prompt,
                )
            except Exception as e:
                logger.error(f"Gemini Vision call failed for field '{field.field_name}': {e}")
                field.fallback_attempted = True
                field.fallback_reason = f"Gemini vision error: {str(e)}"
                fallback_results.append(
                    VisionFallbackFieldResult(
                        field_name=field.field_name,
                        action_taken="skipped",
                        ocr_value=field.field_value,
                        ocr_confidence=field.confidence,
                        reason=f"Gemini vision request failed: {str(e)}",
                        crop_box=clamped_bbox,
                        page_number=field.page_number,
                    )
                )
                continue

            # 4. Evaluate outcome
            eval_res = self.evaluate_recovery(field, vision_out, candidate_reason, clamped_bbox)
            fallback_results.append(eval_res)

            if eval_res.action_taken == "recovered":
                recovered_count += 1
            elif eval_res.action_taken == "conflict":
                conflict_count += 1

            # 5. Re-normalize individual field if recovered or agreed
            if eval_res.action_taken in ("recovered", "agreed"):
                norm_val, is_err, err_msg = FieldNormalizer.normalize_field(field)
                field.normalized_value = norm_val
                field.normalized_at = datetime.utcnow().isoformat()
                if is_err and err_msg:
                    field.validation_status = ValidationStatusEnum.NEEDS_REVIEW.value
                    field.validation_message = err_msg

        # 6. Re-validate document
        validator = DocumentValidator(tolerance=settings.INVOICE_ROUNDING_TOLERANCE)
        updated_validation = validator.validate_document(
            document_id=document_id,
            document_type=doc_type,
            fields=fields,
            section_data=section_data,
        )

        res = DocumentVisionFallbackResult(
            document_id=document_id,
            document_type=doc_type,
            status="completed",
            candidates_identified=len(candidates),
            fields_recovered=recovered_count,
            conflicts_detected=conflict_count,
            fallback_fields=fallback_results,
            fields=fields,
            updated_validation=updated_validation,
            processed_at=now_iso,
            metadata={
                "candidates_count": len(candidates),
                "recovered_count": recovered_count,
                "conflict_count": conflict_count,
                "confidence_threshold": settings.VISION_FALLBACK_CONFIDENCE_THRESHOLD,
            },
        )

        self._save_results(doc_dir, res, updated_validation)
        return res

    def _save_results(
        self,
        doc_dir: Path,
        result: DocumentVisionFallbackResult,
        updated_validation: Optional[DocumentValidationResult] = None,
    ):
        """Persists vision_fallback.json and updates validation.json."""
        try:
            doc_dir.mkdir(parents=True, exist_ok=True)

            fallback_file = doc_dir / "vision_fallback.json"
            with open(fallback_file, "w", encoding="utf-8") as f:
                json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)

            if updated_validation:
                val_file = doc_dir / "validation.json"
                with open(val_file, "w", encoding="utf-8") as f:
                    json.dump(updated_validation.model_dump(), f, indent=2, ensure_ascii=False)

            logger.info(f"Successfully saved vision fallback results to {fallback_file}")
        except Exception as e:
            logger.error(f"Failed to persist vision fallback results: {e}")


vision_fallback_manager = VisionFallbackManager()
