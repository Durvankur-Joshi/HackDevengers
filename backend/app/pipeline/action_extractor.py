import json
import logging
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from app.core.config import settings
from app.pipeline.types import (
    ActionItem,
    ActionPriorityEnum,
    ActionStatusEnum,
    DocumentActionsResult,
    DocumentValidationResult,
    ExtractedField,
    ValidationStatusEnum,
)
from app.services.gemini import gemini_service, GeminiService
from app.services.supabase import supabase_service

logger = logging.getLogger(__name__)


def normalize_action_key(action_text: str) -> str:
    """Normalizes action text for robust deduplication comparison."""
    return re.sub(r"[^a-zA-Z0-9]", "", action_text.lower())


class DocumentActionExtractor:
    """
    Intelligent action extraction engine combining deterministic business rules
    and structured Gemini reasoning to derive concrete, prioritized next steps.
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

    def extract_deterministic_actions(
        self,
        document_id: str,
        document_type: str,
        fields: List[ExtractedField],
        validation_result: Optional[DocumentValidationResult] = None,
    ) -> List[ActionItem]:
        """
        Derives deterministic action items from structured fields and validation issues.
        """
        actions: List[ActionItem] = []
        field_map = {f.field_name.lower(): f for f in fields}
        now = datetime.utcnow().date()

        # ==============================================================================
        # 1. Invoice Deterministic Actions
        # ==============================================================================
        if document_type == "invoice":
            total_f = field_map.get("total_amount") or field_map.get("total") or field_map.get("invoice_total")
            due_f = field_map.get("due_date") or field_map.get("payment_due_date")
            curr_f = field_map.get("currency") or field_map.get("currency_symbol")
            vendor_f = field_map.get("vendor_name") or field_map.get("vendor") or field_map.get("supplier_name")

            curr_code = (curr_f.normalized_value or curr_f.field_value) if curr_f else "USD"
            vendor_name = (vendor_f.normalized_value or vendor_f.field_value) if vendor_f else None

            # A. Payment Action if total exists and is positive
            if total_f and total_f.normalized_value:
                try:
                    total_num = float(total_f.normalized_value)
                    if total_num > 0:
                        due_date_str = due_f.normalized_value if (due_f and due_f.normalized_value) else None

                        # Determine priority grounded in due date
                        priority = ActionPriorityEnum.MEDIUM.value
                        reason = "Payment required for billed invoice."

                        if due_date_str:
                            try:
                                due_dt = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                                if due_dt < now:
                                    priority = ActionPriorityEnum.HIGH.value
                                    reason = f"Payment is overdue since {due_date_str}."
                                elif (due_dt - now).days <= 7:
                                    priority = ActionPriorityEnum.HIGH.value
                                    reason = f"Payment due date ({due_date_str}) is approaching within 7 days."
                                else:
                                    reason = f"Invoice payable by due date {due_date_str}."
                            except ValueError:
                                pass

                        action_text = f"Pay invoice totaling {curr_code} {total_num:,.2f}"
                        if vendor_name:
                            action_text += f" to {vendor_name}"

                        actions.append(
                            ActionItem(
                                document_id=document_id,
                                action=action_text,
                                priority=priority,
                                due_date=due_date_str,
                                status=ActionStatusEnum.PENDING.value,
                                source="rule_based",
                                reason=reason,
                            )
                        )
                except (ValueError, TypeError):
                    pass

        # ==============================================================================
        # 2. Validation Issues Derived Actions (Invoices & Onboarding)
        # ==============================================================================
        issues = validation_result.validation_issues if validation_result else []
        for issue in issues:
            fname = (issue.get("field_name") or "").strip()
            msg = (issue.get("message") or "").strip()
            status = issue.get("status")

            # Check conflict
            if status == ValidationStatusEnum.CONFLICT.value:
                actions.append(
                    ActionItem(
                        document_id=document_id,
                        action=f"Review conflicting values for '{fname}'",
                        priority=ActionPriorityEnum.HIGH.value,
                        due_date=None,  # No due date for conflict resolution
                        status=ActionStatusEnum.PENDING.value,
                        source="rule_based",
                        reason=f"Validation conflict: {msg}",
                    )
                )
                continue

            # Arithmetic discrepancy
            if "discrepancy" in msg.lower() or "does not match" in msg.lower() or "!=" in msg or "mismatch" in msg.lower() or issue.get("code") == "ARITHMETIC_MISMATCH":
                actions.append(
                    ActionItem(
                        document_id=document_id,
                        action=f"Resolve calculation discrepancy on '{fname}'",
                        priority=ActionPriorityEnum.HIGH.value,
                        due_date=None,
                        status=ActionStatusEnum.PENDING.value,
                        source="rule_based",
                        reason=msg,
                    )
                )
                continue

            # Date relationship error
            if "earlier than invoice date" in msg.lower():
                actions.append(
                    ActionItem(
                        document_id=document_id,
                        action="Clarify invalid invoice due date with vendor",
                        priority=ActionPriorityEnum.HIGH.value,
                        due_date=None,
                        status=ActionStatusEnum.PENDING.value,
                        source="rule_based",
                        reason=msg,
                    )
                )
                continue

            # Missing required field
            if "missing" in msg.lower() or issue.get("code") == "REQUIRED_FIELD_MISSING":
                actions.append(
                    ActionItem(
                        document_id=document_id,
                        action=f"Obtain missing required information for '{fname}'",
                        priority=ActionPriorityEnum.HIGH.value,
                        due_date=None,
                        status=ActionStatusEnum.PENDING.value,
                        source="rule_based",
                        reason=msg,
                    )
                )
                continue

            # Format error
            if "invalid" in msg.lower() or "must contain" in msg.lower():
                actions.append(
                    ActionItem(
                        document_id=document_id,
                        action=f"Verify and correct invalid format for '{fname}'",
                        priority=ActionPriorityEnum.MEDIUM.value,
                        due_date=None,
                        status=ActionStatusEnum.PENDING.value,
                        source="deterministic",
                        reason=msg,
                    )
                )

        # ==============================================================================
        # 3. Onboarding Specific Actions
        # ==============================================================================
        if document_type == "onboarding_form":
            name_f = field_map.get("full_name")
            join_f = field_map.get("joining_date")
            dept_f = field_map.get("department")

            cand_name = (name_f.normalized_value or name_f.field_value) if name_f else "new employee"

            if join_f and join_f.normalized_value:
                actions.append(
                    ActionItem(
                        document_id=document_id,
                        action=f"Prepare onboarding provisioning for {cand_name}",
                        priority=ActionPriorityEnum.MEDIUM.value,
                        due_date=join_f.normalized_value,
                        status=ActionStatusEnum.PENDING.value,
                        source="deterministic",
                        reason=f"Candidate joining date is scheduled for {join_f.normalized_value}.",
                    )
                )

        return actions

    def extract_ai_actions(
        self,
        document_id: str,
        document_type: str,
        fields: List[ExtractedField],
        deterministic_actions: List[ActionItem],
    ) -> List[ActionItem]:
        """
        Uses Gemini to identify contextual business follow-ups not covered by deterministic rules.
        """
        # Prepare compact context
        existing_action_texts = [a.action for a in deterministic_actions]
        field_summary = []
        for f in fields:
            val = f.normalized_value if f.normalized_value is not None else f.field_value
            if val is not None and str(val).strip():
                field_summary.append(f"{f.field_name}: {val}")

        prompt = f"""You are an executive operations workflow assistant.
Given the structured document data below, identify up to 3 concrete, high-priority operational tasks that human operators or departments must take.

DOCUMENT TYPE: {document_type}
EXTRACTED FIELDS:
{chr(10).join(field_summary[:25])}

ALREADY IDENTIFIED ACTIONS (DO NOT DUPLICATE THESE):
{json.dumps(existing_action_texts, indent=2)}

STRICT OPERATIONAL RULES:
1. ONLY suggest concrete next steps that logically follow from the documented facts (e.g. "Confirm wire transfer banking details with vendor", "Verify employee tax exemption documents").
2. DO NOT create generic placeholders such as "Process this document" or "Review document".
3. DUE DATE RULE: ONLY specify a due_date (YYYY-MM-DD) if an explicit deadline date is present in the extracted fields. Otherwise set due_date to null. NEVER invent dates!
4. Priority must be 'high', 'medium', or 'low' grounded in urgency or financial risk.
5. Provide a clear, brief reason explaining the factual ground for each action.
"""
        try:
            ai_out = self.gemini.suggest_contextual_actions(prompt)
            ai_actions = []
            for raw in ai_out.actions:
                ai_actions.append(
                    ActionItem(
                        document_id=document_id,
                        action=raw.action,
                        priority=raw.priority,
                        due_date=raw.due_date,
                        status=ActionStatusEnum.PENDING.value,
                        source="ai",
                        reason=raw.reason,
                    )
                )
            return ai_actions
        except Exception as e:
            logger.warning(f"AI contextual action extraction failed: {e}. Relying solely on deterministic actions.")
            return []

    def extract_actions(
        self,
        document_id: str,
        document_type: Optional[str] = None,
        fields: Optional[List[ExtractedField]] = None,
        validation_result: Optional[DocumentValidationResult] = None,
    ) -> DocumentActionsResult:
        """
        Main entry point for Phase 11 action extraction.
        Extracts, deduplicates, and idempotently persists actions while preserving user modifications.
        """
        doc_dir = Path(self.base_dir) / document_id
        now_iso = datetime.utcnow().isoformat()

        if isinstance(fields, DocumentValidationResult):
            validation_result = fields
            fields = validation_result.fields

        # Step 1: Resolve fields and validation result if not provided
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

        # Fallback to extraction.json
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

        # Step 2: Skip unknown document type
        if doc_type == "unknown":
            logger.info(f"Skipping action extraction for document {document_id} of unknown type.")
            result = DocumentActionsResult(
                document_id=document_id,
                document_type="unknown",
                status="skipped",
                total_actions=0,
                high_priority_count=0,
                actions=[],
                extracted_at=now_iso,
                metadata={"message": "Unsupported document type for action extraction."},
            )
            self._save_actions(doc_dir, document_id, result)
            return result

        # Step 3: Extract deterministic actions
        det_actions = self.extract_deterministic_actions(document_id, doc_type, fields, validation_result)

        # Step 4: Extract AI contextual actions
        ai_actions = self.extract_ai_actions(document_id, doc_type, fields, det_actions)

        # Step 5: Deduplicate combined actions
        combined: List[ActionItem] = []
        seen_keys: Set[str] = set()

        for a in det_actions + ai_actions:
            key = normalize_action_key(a.action)
            if key not in seen_keys:
                seen_keys.add(key)
                combined.append(a)

        # Limit total actions to avoid cognitive overload
        combined = combined[:settings.ACTIONS_MAX_COUNT]

        # Step 6: Idempotency & User Status Preservation
        final_actions = self._reconcile_with_existing_actions(document_id, combined)

        total_actions = len(final_actions)
        high_priority_count = sum(1 for a in final_actions if a.priority == ActionPriorityEnum.HIGH.value)

        result = DocumentActionsResult(
            document_id=document_id,
            document_type=doc_type,
            status="completed",
            total_actions=total_actions,
            high_priority_count=high_priority_count,
            actions=final_actions,
            extracted_at=now_iso,
            metadata={
                "total_actions": total_actions,
                "deterministic_count": sum(1 for a in final_actions if a.source == "deterministic"),
                "ai_count": sum(1 for a in final_actions if a.source == "ai"),
                "high_priority_count": high_priority_count,
            },
        )

        self._save_actions(doc_dir, document_id, result)
        return result

    def _reconcile_with_existing_actions(
        self, document_id: str, new_actions: List[ActionItem]
    ) -> List[ActionItem]:
        """
        Synchronizes newly generated actions with existing actions in database/disk.
        CRITICAL: Preserves user-modified statuses ('completed', 'in_progress') on re-run.
        """
        existing_actions: List[Dict[str, Any]] = []

        # Try to fetch existing actions from database
        try:
            if supabase_service.is_configured():
                existing_actions = supabase_service.get_actions(document_id)
        except Exception as e:
            logger.warning(f"Could not load existing actions from Supabase for doc {document_id}: {e}")

        # Fallback to local actions.json if DB query returned nothing
        if not existing_actions:
            local_file = Path(self.base_dir) / document_id / "actions.json"
            if local_file.exists():
                try:
                    with open(local_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    existing_actions = data.get("actions", [])
                except Exception:
                    pass

        # Index existing actions by normalized action key
        existing_map: Dict[str, Dict[str, Any]] = {}
        for ea in existing_actions:
            act_text = ea.get("action", "")
            if act_text:
                existing_map[normalize_action_key(act_text)] = ea

        reconciled: List[ActionItem] = []
        for na in new_actions:
            key = normalize_action_key(na.action)
            if key in existing_map:
                ea = existing_map[key]
                # Preserve existing action ID
                na.id = ea.get("id")
                # Preserve user modified status
                user_status = ea.get("status")
                if user_status in ("completed", "in_progress", "dismissed"):
                    na.status = user_status
                # Preserve existing created_at
                na.created_at = ea.get("created_at")
            reconciled.append(na)

        # Also preserve any manual actions created directly by the user that were not in generated list
        for key, ea in existing_map.items():
            if not any(normalize_action_key(r.action) == key for r in reconciled):
                if ea.get("source") == "user" or ea.get("status") in ("completed", "in_progress"):
                    reconciled.append(ActionItem.model_validate(ea))

        return reconciled

    def _save_actions(self, doc_dir: Path, document_id: str, result: DocumentActionsResult):
        """Persists actions artifact to disk and synchronizes with Supabase database."""
        try:
            doc_dir.mkdir(parents=True, exist_ok=True)
            actions_file = doc_dir / "actions.json"
            with open(actions_file, "w", encoding="utf-8") as f:
                json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)
            logger.info(f"Saved actions artifact for {document_id} to {actions_file}")
        except Exception as e:
            logger.error(f"Failed to write actions.json for {document_id}: {e}")

        # Synchronize with Supabase actions table
        if result.status == "completed" and result.actions:
            try:
                if supabase_service.is_configured():
                    supabase_service.save_actions(document_id, [a.model_dump() for a in result.actions])
            except Exception as db_err:
                logger.warning(f"Could not persist actions to Supabase for {document_id}: {db_err}")


document_action_extractor = DocumentActionExtractor()
