-- ==============================================================================
-- Migration: Phase 9 Normalization & Deterministic Validation Columns
-- Purpose: Add normalized_value, validation_status, validation_message, and normalized_at
--          to the extracted_fields table.
-- ==============================================================================

-- 1. Add columns if not existing
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS normalized_value TEXT NULL;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS validation_status TEXT NULL;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS validation_message TEXT NULL;
ALTER TABLE extracted_fields ADD COLUMN IF NOT EXISTS normalized_at TIMESTAMPTZ NULL;

-- 2. Add validation status check constraint
ALTER TABLE extracted_fields DROP CONSTRAINT IF EXISTS chk_extracted_fields_validation_status;
ALTER TABLE extracted_fields ADD CONSTRAINT chk_extracted_fields_validation_status 
CHECK (validation_status IS NULL OR validation_status IN ('valid', 'needs_review', 'conflict'));
