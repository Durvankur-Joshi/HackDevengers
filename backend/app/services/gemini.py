import json
import logging
from typing import Optional, Type, Any
from app.core.config import settings
from app.pipeline.types import (
    GeminiClassificationOutput,
    DocumentType,
    GeminiSectionDetectionOutput,
    GeminiRawSection,
)

logger = logging.getLogger(__name__)


class GeminiServiceError(Exception):
    """Base exception for Gemini service issues."""
    pass


class GeminiNotConfiguredError(GeminiServiceError):
    """Raised when GEMINI_API_KEY is missing or invalid."""
    pass


class GeminiService:
    """
    Encapsulated Google Gemini service for layout-aware semantic parsing and classification.
    Adheres strictly to typed Pydantic output schemas.
    """

    def __init__(self):
        self._client = None

    def is_configured(self) -> bool:
        """Check whether valid Gemini API key is configured."""
        key = (settings.GEMINI_API_KEY or "").strip()
        return bool(key)

    def get_client(self):
        """Lazily initialize and return the Google GenAI SDK client."""
        if not self.is_configured():
            raise GeminiNotConfiguredError(
                "Gemini API key is not configured. Please set GEMINI_API_KEY in backend/.env."
            )

        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=settings.GEMINI_API_KEY.strip())
                logger.info("Google GenAI client successfully initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Google GenAI client: {e}")
                raise GeminiServiceError(f"Failed to initialize Gemini client: {str(e)}")

        return self._client

    def classify_content(self, prompt: str) -> GeminiClassificationOutput:
        """
        Execute semantic document classification via Gemini structured output.
        Returns validated GeminiClassificationOutput instance.
        """
        client = self.get_client()
        model_name = settings.GEMINI_MODEL or "gemini-2.5-flash"

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiClassificationOutput,
                temperature=0.1,
            )

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )

            raw_text = response.text
            if not raw_text:
                raise GeminiServiceError("Gemini returned an empty response.")

            # Parse and validate with Pydantic
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError as json_err:
                logger.error(f"Malformed JSON from Gemini: {raw_text}")
                raise GeminiServiceError(f"Gemini returned invalid JSON: {str(json_err)}")

            # Normalize document_type string to match enum
            doc_type_raw = str(data.get("document_type", "")).strip().lower()
            if doc_type_raw not in ("invoice", "onboarding_form", "unknown"):
                logger.warning(f"Unrecognized document type '{doc_type_raw}' returned by Gemini; defaulting to unknown.")
                data["document_type"] = "unknown"

            # Validate confidence float range
            conf = data.get("confidence", 0.0)
            try:
                conf = float(conf)
                data["confidence"] = max(0.0, min(1.0, conf))
            except (ValueError, TypeError):
                data["confidence"] = 0.0

            # Validate evidence is a list of strings
            evidence = data.get("evidence", [])
            if isinstance(evidence, str):
                evidence = [evidence]
            elif not isinstance(evidence, list):
                evidence = []
            data["evidence"] = [str(e).strip() for e in evidence if str(e).strip()]

            return GeminiClassificationOutput.model_validate(data)

        except GeminiServiceError:
            raise
        except Exception as e:
            logger.error(f"Gemini API request failed: {e}")
            raise GeminiServiceError(f"AI classification request failed: {str(e)}")

    def detect_sections(self, prompt: str, model: Optional[str] = None) -> GeminiSectionDetectionOutput:
        """
        Execute structured section detection using Gemini with response_schema enforcement.
        Identifies logical document regions without extracting structured fields.
        """
        client = self.get_client()
        model_name = model or settings.GEMINI_MODEL

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiSectionDetectionOutput,
                temperature=0.1,
            )

            logger.info(f"Calling Gemini model '{model_name}' for section detection...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )

            raw_text = response.text
            if not raw_text:
                raise GeminiServiceError("Gemini returned an empty response for section detection.")

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError as json_err:
                logger.error(f"Malformed JSON from Gemini section detection: {raw_text}")
                raise GeminiServiceError(f"Gemini returned invalid JSON: {str(json_err)}")

            raw_sections = data.get("sections", [])
            if not isinstance(raw_sections, list):
                raw_sections = []

            cleaned_sections = []
            for item in raw_sections:
                if not isinstance(item, dict):
                    continue
                sec_name = str(item.get("section_name", "")).strip().lower()
                sec_text = str(item.get("text", "")).strip()
                if not sec_text:
                    continue

                try:
                    conf = float(item.get("confidence", 0.9))
                    conf = max(0.0, min(1.0, conf))
                except (ValueError, TypeError):
                    conf = 0.8

                try:
                    page_num = int(item.get("page_number", 1))
                except (ValueError, TypeError):
                    page_num = 1

                block_ids = item.get("block_ids", [])
                if isinstance(block_ids, list):
                    cleaned_block_ids = []
                    for b in block_ids:
                        try:
                            cleaned_block_ids.append(int(b))
                        except (ValueError, TypeError):
                            pass
                else:
                    cleaned_block_ids = []

                cleaned_sections.append({
                    "section_name": sec_name,
                    "page_number": page_num,
                    "text": sec_text,
                    "confidence": conf,
                    "block_ids": cleaned_block_ids,
                })

            return GeminiSectionDetectionOutput.model_validate({"sections": cleaned_sections})

        except GeminiServiceError:
            raise
        except Exception as e:
            logger.error(f"Gemini section detection API request failed: {e}")
            raise GeminiServiceError(f"AI section detection request failed: {str(e)}")

    def extract_section_data(
        self,
        prompt: str,
        response_schema: Any,
        model: Optional[str] = None
    ) -> Any:
        """
        Execute targeted structured field extraction using Gemini with response_schema enforcement.
        Receives strictly targeted section text and extracts typed fields into response_schema.
        """
        client = self.get_client()
        model_name = model or settings.GEMINI_MODEL

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.0,
            )

            logger.info(f"Calling Gemini model '{model_name}' for targeted section extraction...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )

            raw_text = response.text
            if not raw_text:
                raise GeminiServiceError("Gemini returned an empty response for section extraction.")

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError as json_err:
                logger.error(f"Malformed JSON from Gemini section extraction: {raw_text}")
                raise GeminiServiceError(f"Gemini returned invalid JSON: {str(json_err)}")

            return response_schema.model_validate(data)

        except GeminiServiceError:
            raise
        except Exception as e:
            logger.error(f"Gemini section extraction API request failed: {e}")
            raise GeminiServiceError(f"AI section extraction request failed: {str(e)}")


gemini_service = GeminiService()
