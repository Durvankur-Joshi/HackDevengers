-- ==============================================================================
-- Document-to-Action Pipeline: Database Schema
-- Phase 2 — Supabase PostgreSQL Schema Definition
-- ==============================================================================

-- Enable UUID extension if not already present
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==============================================================================
-- Function: Auto-update updated_at timestamp
-- ==============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- ==============================================================================
-- Table 1: documents
-- Purpose: Store uploaded document metadata and overall processing state.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    document_type TEXT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    mime_type TEXT NULL,
    file_size BIGINT NULL,
    storage_path TEXT NULL,
    summary TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_documents_status CHECK (
        status IN (
            'uploaded',
            'preprocessing',
            'preprocessed',
            'ocr',
            'ocr_completed',
            'classified',
            'extracting',
            'validating',
            'completed',
            'needs_review',
            'failed'
        )
    ),
    CONSTRAINT chk_documents_type CHECK (
        document_type IS NULL OR document_type IN (
            'invoice',
            'onboarding_form',
            'unknown'
        )
    )
);

-- Ensure storage_path exists if documents table already existed from Phase 2
ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_path TEXT;

-- Update status constraint to support 'ocr_completed' (Phase 5)
ALTER TABLE documents DROP CONSTRAINT IF EXISTS chk_documents_status;
ALTER TABLE documents ADD CONSTRAINT chk_documents_status CHECK (
    status IN (
        'uploaded',
        'preprocessing',
        'preprocessed',
        'ocr',
        'ocr_completed',
        'classified',
        'extracting',
        'validating',
        'completed',
        'needs_review',
        'failed'
    )
);

-- Trigger for documents.updated_at
DROP TRIGGER IF EXISTS trg_documents_updated_at ON documents;
CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==============================================================================
-- Table 2: document_sections
-- Purpose: Store logical sections detected inside a document.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS document_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_name TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    page_number INTEGER NULL,
    confidence NUMERIC(5, 4) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ==============================================================================
-- Table 3: extracted_fields
-- Purpose: Store structured values extracted from document sections with provenance.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS extracted_fields (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id UUID NULL REFERENCES document_sections(id) ON DELETE SET NULL,
    field_name TEXT NOT NULL,
    field_value TEXT NULL,
    confidence NUMERIC(5, 4) NULL,
    source TEXT NULL,
    source_text TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_extracted_fields_source CHECK (
        source IS NULL OR source IN ('ocr', 'gemini', 'vision', 'manual')
    )
);

-- ==============================================================================
-- Table 4: actions
-- Purpose: Store actionable tasks derived from validated document information.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    due_date DATE NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_actions_priority CHECK (
        priority IN ('low', 'medium', 'high')
    ),
    CONSTRAINT chk_actions_status CHECK (
        status IN ('pending', 'completed', 'dismissed')
    )
);

-- Trigger for actions.updated_at
DROP TRIGGER IF EXISTS trg_actions_updated_at ON actions;
CREATE TRIGGER trg_actions_updated_at
    BEFORE UPDATE ON actions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==============================================================================
-- Table 5: processing_logs
-- Purpose: Track audit logs and stage transitions during document processing.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS processing_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NULL,
    metadata JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ==============================================================================
-- Indexes for Optimal Performance
-- ==============================================================================

-- documents indexes
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_document_type ON documents(document_type);

-- document_sections indexes
CREATE INDEX IF NOT EXISTS idx_document_sections_document_id ON document_sections(document_id);

-- extracted_fields indexes
CREATE INDEX IF NOT EXISTS idx_extracted_fields_document_id ON extracted_fields(document_id);
CREATE INDEX IF NOT EXISTS idx_extracted_fields_section_id ON extracted_fields(section_id);

-- actions indexes
CREATE INDEX IF NOT EXISTS idx_actions_document_id ON actions(document_id);
CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
CREATE INDEX IF NOT EXISTS idx_actions_due_date ON actions(due_date);

-- processing_logs indexes
CREATE INDEX IF NOT EXISTS idx_processing_logs_document_id ON processing_logs(document_id);
CREATE INDEX IF NOT EXISTS idx_processing_logs_created_at ON processing_logs(created_at DESC);
