-- ==============================================================================
-- Migration: Phase 10 Low-Confidence & Handwriting Vision Fallback Columns
-- Purpose: Add OCR provenance, Vision fallback readings, fallback flags, and 
--          expand source check constraints on the extracted_fields table.
-- ==============================================================================

-- 1. Add Phase 10 vision fallback and provenance columns if not existing
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS ocr_value TEXT NULL;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS ocr_confidence NUMERIC(5, 4) NULL;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS vision_value TEXT NULL;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS vision_confidence NUMERIC(5, 4) NULL;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS vision_source_text TEXT NULL;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS fallback_attempted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS fallback_reason TEXT NULL;

-- 2. Update source check constraint to allow vision_fallback and ocr+vision
ALTER TABLE extracted_fields DROP CONSTRAINT IF EXISTS chk_extracted_fields_source;
ALTER TABLE extracted_fields ADD CONSTRAINT chk_extracted_fields_source 
CHECK (
    source IS NULL OR source IN ('ocr', 'gemini', 'vision', 'vision_fallback', 'ocr+vision', 'manual', 'validation')
);
