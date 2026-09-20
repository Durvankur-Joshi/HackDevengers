-- ==============================================================================
-- Migration: Phase 11 Intelligent Summary & Action Extraction
-- Purpose: Add reason and source columns to actions table, update action status 
--          constraint to support 'in_progress', and update documents status constraint.
-- ==============================================================================

-- 1. Add reason and source columns to actions table if not existing
ALTER TABLE actions ADD COLUMN IF NOT EXISTS reason TEXT NULL;
ALTER TABLE actions ADD COLUMN IF NOT EXISTS source TEXT NULL DEFAULT 'system';

-- 2. Update actions status check constraint to include 'in_progress'
ALTER TABLE actions DROP CONSTRAINT IF EXISTS chk_actions_status;
ALTER TABLE actions ADD CONSTRAINT chk_actions_status 
CHECK (status IN ('pending', 'in_progress', 'completed', 'dismissed'));

-- 3. Update documents status check constraint for Phase 11 stages
ALTER TABLE documents DROP CONSTRAINT IF EXISTS chk_documents_status;
ALTER TABLE documents ADD CONSTRAINT chk_documents_status CHECK (
    status IN (
        'uploaded',
        'preprocessing',
        'preprocessed',
        'ocr',
        'ocr_completed',
        'classified',
        'sectioned',
        'extracting',
        'extracted',
        'validating',
        'completed',
        'needs_review',
        'failed',
        'summarizing',
        'summarized',
        'extracting_actions'
    )
);
