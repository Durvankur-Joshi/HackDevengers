# System Architecture & Technical Constitution

Document-to-Action Pipeline
===========================

This document outlines the complete architectural design, modular contracts, data flow, and technical constitution for the **Document-to-Action Pipeline**.

---

## 1. System Overview

The **Document-to-Action Pipeline** is an enterprise-grade document intelligence system designed for a 24-hour hackathon implementation. It converts unstructured, noisy physical documents (e.g., scanned invoices and multi-section onboarding forms) into structured, validated, and actionable data.

### Architectural Tenet: Decoupled Intelligence vs. Monolithic LLM
A central anti-pattern in modern hackathon projects is the **"Document → LLM → Everything"** approach, which passes raw images/PDFs directly to an LLM and expects zero-shot flawless extraction, arithmetic validation, and action synthesis. 

This architecture rejects that anti-pattern:
- **Local Preprocessing & OCR**: Extracts deterministic text tokens, layout coordinates, and confidence scores first.
- **Isolated Gemini Service**: Invokes Google Gemini strictly for targeted semantic parsing into strongly typed schemas using layout-grounded text.
- **Independent Deterministic Validation**: Computes arithmetic line-item reconciliations, presence checks, and format constraints outside the LLM.
- **Structured Downstream Processing**: Generates operational summaries and action items directly from validated schemas, never from raw re-ingestion of the original file.

### High-Level Architecture Diagram

```
+-------------------------------------------------------------------+
|                        React Dashboard (Vite)                     |
|         (Document Uploader, Extracted Fields, Action Board)       |
+-------------------------------------------------------------------+
                                  │
                                  ▼ HTTP / REST
+-------------------------------------------------------------------+
|                      FastAPI API Gateway                          |
|         (Routes: /upload, /documents, /pipeline/process)          |
+-------------------------------------------------------------------+
                                  │
                                  ▼ Hand-off
+-------------------------------------------------------------------+
|                  Pipeline Orchestrator Layer                      |
|                  (Coordinates Pipeline Stages)                    |
+-------------------------------------------------------------------+
                                  │
      ┌───────────────────────────┴───────────────────────────┐
      ▼                                                       ▼
[Stage 1: Preprocessing]                              [Stage 2: OCR Extraction]
 - Clean contrast & deskew                             - Token & block extraction
 - Format standardization                              - Bounding boxes & confidence
      │                                                       │
      └───────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
[Stage 3: Document Classification]
 - Classify: Invoice / Bill vs. Onboarding Form
                                  │
                                  ▼
[Stage 4: Section Detection]
 - Segment into functional text blocks (Header, Line Items, Personal, etc.)
                                  │
                                  ▼
[Stage 5: Gemini Structured Extraction] ◄─── (Isolated Gemini Service)
 - Strict Pydantic schemas (InvoiceSchema, OnboardingSchema)
 - Layout-aware contextual structuring
                                  │
                                  ▼
[Stage 6: Normalization]
 - Standardize dates (ISO 8601), currency floats, phone numbers
                                  │
                                  ▼
[Stage 7: Deterministic Validation] ◄─────── (Pure Business Logic)
 - Total = Subtotal + Tax verification
 - Required fields, valid dates, regex constraints
                                  │
                                  ▼
[Stage 8: Summary & Action Extraction]
 - Executive overview generation
 - Prioritized operational action items (Approve, Notify, Review)
                                  │
                                  ▼
+-------------------------------------------------------------------+
|                     Database Service Layer                        |
|                  (Supabase PostgreSQL Client)                     |
+-------------------------------------------------------------------+
                                  │
                                  ▼
+-------------------------------------------------------------------+
|                      Supabase PostgreSQL                          |
|      (Tables: documents, document_sections, field_extractions,   |
|               validations, action_items)                          |
+-------------------------------------------------------------------+
                                  │
                                  ▼ Real-time Query / Polling
+-------------------------------------------------------------------+
|                       React Dashboard                             |
|               (Displays validated data & actions)                 |
+-------------------------------------------------------------------+
```

### Document Ingestion Flow (Phase 3)

```
React Frontend (DocumentUpload Component / Drag-and-Drop)
    │
    ▼ multipart/form-data (PDF, JPG, PNG <= 10MB)
FastAPI Backend (POST /api/documents/upload)
    │
    ├──► File Validation (MIME type verification & sanitization)
    ├──► Supabase Storage Layer (Binary storage in 'documents/{uuid}/{filename}')
    ├──► Supabase PostgreSQL (Row in 'documents' table, status='uploaded')
    └──► Audit Logger (Row in 'processing_logs' table, stage='upload')
    │
    ▼ JSON Response
Frontend Preview (Document Card + Temporary Signed URL Access)
```

### Document Preprocessing Flow (Phase 4)

```
React Frontend ([ Prepare for OCR ] Button)
    │
    ▼ POST /api/documents/{document_id}/preprocess
FastAPI Backend (pipeline/preprocessing.py)
    │
    ├──► Fetch original file from Supabase Storage (download_file)
    ├──► Format & Type Inspection (PDF vs. Image: JPG / PNG)
    ├──► PDF Branch (PyMuPDF / fitz):
    │     - Iterate pages in 1-based sequential order
    │     - Render each page at 200 DPI RGB pixmap (2.7778x zoom)
    ├──► Image Branch (Pillow):
    │     - Auto-orient based on EXIF tags
    │     - Composite RGBA/Palette onto pure white RGB background
    │     - Constrain maximum dimensions <= 2400px (LANCZOS resample)
    │     - Enhance contrast slightly (factor 1.15) for crisp text edges
    ├──► Idempotent Local Storage:
    │     - Wipe existing directory backend/tmp/processing/{document_id}/
    │     - Save to page_{page_num:03d}.png with 0600 file permissions
    ├──► Database Status & Audit Log:
    │     - Update 'documents' status: 'uploaded' -> 'preprocessing' -> 'preprocessed'
    │     - Record duration, page count, and resolution in 'processing_logs' table
    │
    ▼ JSON Response: PreprocessingResult (PreprocessedPage[])
[Phase 5: OCR Engine consumes 200 DPI normalized PNGs independently]
```

### OCR Extraction & Layout-Aware Representation (Phase 5)

```
Document
↓
Preprocessing
↓
OCR (Tesseract Engine via pytesseract)
↓
OCR Result
├── Full Text (Multi-page with delimiters)
├── Blocks (Ordered text lines)
├── Bounding Boxes (x, y, width, height in pixels)
└── Confidence (Block & Document Average)
```

> **Decoupled Architecture Rule**: The OCR layer is an independent service isolated from both preprocessing and semantic reasoning. OCR is intentionally separated from Gemini-based semantic extraction: OCR produces grounded physical text tokens with pixel bounding boxes and confidence metrics without invoking LLMs. Gemini is only invoked downstream for schema structuring.

### Document Classification (Phase 6)

```
OCR Result
↓
Classification Input Builder (Bounded layout-aware text)
↓
Gemini Semantic Classifier (response_schema=GeminiClassificationOutput)
↓
Confidence Threshold Filter (default >= 0.70)
↓
Classification Result
├── invoice
├── onboarding_form
└── unknown
```

> **Decoupled Architecture Rule**: Classification uses structured OCR output (not raw images/PDFs) and Google Gemini semantic understanding. Gemini categorizes the document strictly into `invoice`, `onboarding_form`, or `unknown`. Any document that does not explicitly match the two supported archetypes (e.g. resumes, portfolios, general letters, menus) or falls below the confidence threshold is deterministically routed to `unknown`.

### Section Detection (Phase 7)

```
OCR Result (ocr.json) + Classification (classification.json)
↓
Pre-routing Check:
  - If document_type == 'unknown' -> return [] immediately (Bypass LLM)
  - If invoice / onboarding_form -> Proceed
↓
Structure Analyzer Prompt Builder (Forbids field extraction)
↓
Gemini Section Detector (response_schema=GeminiSectionDetectionOutput)
↓
Section Whitelist Validation (Maps unrecognized sections to 'unknown')
↓
Bounding Box Union Mapping (From OCR Block Coordinates)
↓
Storage & Persistence:
  - Save sections.json local artifact
  - Persist to Supabase document_sections table
  - Update documents status='sectioned' and log audit metrics
```

> **Decoupled Architecture Rule**: Section Detection is strictly a layout and regional segmentation stage. It identifies logical boundaries (`vendor_information`, `line_items`, `personal_information`, etc.) without extracting granular field values (such as names, dates, amounts, taxes). Field extraction is reserved exclusively for Phase 8.

### Targeted Structured AI Extraction (Phase 8)

```
DocumentSectionResult (sections.json) + Classification (classification.json)
↓
Archetype Gate:
  - If document_type == 'unknown' -> return {"status": "skipped", "reason": "Unsupported document type"}
  - If invoice / onboarding_form -> Proceed to section-by-section extraction
↓
Iterate Each Detected Section:
  ├── Look up Section Schema (e.g. vendor_information -> VendorInfoExtraction)
  ├── Build Targeted Prompt:
  │     - Contains ONLY current section text
  │     - STRICT NULL POLICY: Return null for missing fields (No Hallucination / Inference)
  │     - NO ARITHMETIC RECALCULATION: Reserved for Phase 9 Validation
  ├── Dispatch to Gemini (gemini-2.5-flash) with Pydantic response_schema
  └── Convert to Standardized Field Provenance Records:
        - field_name, field_value, confidence, source='gemini', source_text, section_name, page_number
↓
Storage & Persistence:
  ├── Save extraction.json local artifact
  ├── Insert rows into Supabase extracted_fields table
  ├── Update documents status='extracted'
  └── Record processing_logs audit entry (stage='extraction')
```

#### Section-Specific Extraction Schema Hierarchy

```
Section Detection
↓
Targeted Gemini Extraction
├── Vendor Schema
├── Customer Schema
├── Invoice Schema
├── Line Item Schema
└── Payment Schema

and:

Onboarding
├── Personal Schema
├── Contact Schema
├── Employment Schema
└── Identity Schema
```

> **Targeted Extraction Architectural Rule**: Gemini receives section-level input rather than the original document as a whole. The system strictly forbids passing the entire original PDF or full OCR text to Gemini for extraction. Instead, Gemini receives only the text of the targeted section and its corresponding schema. This drastically reduces token overhead, eliminates cross-section context contamination, and guarantees layout grounding. Missing fields strictly default to `null` rather than fabricated or inferred values.

---

## 2. Frontend Architecture

The frontend is built using **React 18+**, bundled with **Vite**, styled with **Tailwind CSS**, and accented with **shadcn/ui** accessible primitives.

### Core Modules
1. **Document Intake Hub**:
   - Drag-and-drop document upload (PDF, PNG, JPG).
   - Instant visual preview with zoom/pan capabilities.
2. **Processing Status Indicator**:
   - Visual step-by-step progress tracking reflecting the orchestrator's pipeline stages (Upload → OCR → Classification → Extraction → Validation → Ready).
3. **Structured Inspector & Side-by-Side Review**:
   - Left pane: Document viewer displaying the original file.
   - Right pane: Structured, collapsible sections (Vendor Info, Line Items, Personal Data).
   - Visual badges for field confidence and validation passes/failures.
4. **Action Items & Resolution Board**:
   - Dedicated interactive task list derived from document actions (e.g., "Review unverified tax amount", "Schedule payment for 2026-10-01", "Request missing ID document").
   - Status toggles (Pending, Approved, Dismissed).

### State & API Management
- Clean API client isolating backend fetch calls.
- Optimistic local state for action toggling.
- No heavy state management library required; React standard state/context provides maximum simplicity for hackathon velocity.

---

## 3. Backend Architecture

The backend is built in **Python 3.11+** with **FastAPI**, emphasizing modular layer separation:

```
backend/
├── app/
│   ├── api/              # API route controllers (thin HTTP layer)
│   │   ├── routes/
│   │   │   ├── documents.py
│   │   │   └── pipeline.py
│   │   └── router.py
│   ├── core/             # Configuration, logging, global settings
│   │   └── config.py
│   ├── schemas/          # Pydantic schemas for API and AI contracts
│   │   ├── common.py
│   │   ├── invoice.py
│   │   ├── onboarding.py
│   │   └── actions.py
│   ├── services/         # Isolated third-party integrations
│   │   ├── ocr/          # OCR provider interface + implementations
│   │   │   ├── base.py
│   │   │   └── tesseract_or_vision.py
│   │   ├── gemini/       # Isolated Gemini API client
│   │   │   ├── client.py
│   │   │   └── prompts.py
│   │   └── db/           # Database access layer
│   │       ├── client.py
│   │       └── repository.py
│   └── pipeline/         # Modular pipeline orchestration & stages
│       ├── orchestrator.py
│       ├── preprocessor.py
│       ├── classifier.py
│       ├── section_detector.py
│       ├── normalizer.py
│       ├── validator.py
│       └── action_extractor.py
└── main.py
```

### Key Separation Rules
- **Thin Controllers**: `api/` routes only handle HTTP parameters, multipart uploads, and JSON serialization. They do not execute pipeline logic.
- **Pipeline Orchestrator**: `pipeline/orchestrator.py` receives a file stream or path, invokes pipeline steps sequentially, records timing/metadata, and returns a unified pipeline execution payload.
- **Pluggable OCR Interface**: `services/ocr/base.py` defines a standard `BaseOCRService` interface with `extract_text_and_layout()`. Swapping OCR backends requires changing one file, not the application.
- **Isolated Database Service**: `services/db/repository.py` handles all Supabase/PostgreSQL interactions. The pipeline code never executes direct SQL or raw Supabase queries.

---

## 4. AI Architecture (Google Gemini Integration)

### Role of Gemini in the System
Google Gemini is treated as a high-precision semantic parsing engine, not an end-to-end black box. Gemini is invoked only after OCR has digitized the text and spatial layout.

### Extraction Strategy: Layout-Aware Structured Output
1. **Input Payload to Gemini**:
   - Extracted text organized by detected sections.
   - Positional cues and section labels.
   - Clear system prompt instructing strict schema adherence.
2. **Strict Schema Conformance**:
   - Extraction uses Gemini's structured output capability (`response_mime_type="application/json"` with Pydantic schema validation).
3. **Prompt Isolation**:
   - Prompts are defined in dedicated modules (`services/gemini/prompts.py`), versioned and separated by document type (`INVOICE_EXTRACTION_PROMPT`, `ONBOARDING_EXTRACTION_PROMPT`).

### Target Schemas

#### 1. Invoice / Bill Schema
- **Vendor Information**: Name, Address, Tax ID / VAT Number, Contact.
- **Customer Information**: Name, Billing Address, Shipping Address, Account Number.
- **Invoice Details**: Invoice Number, Issue Date, Due Date, Purchase Order (PO) Number.
- **Line Items**: Array of items (Description, Quantity, Unit Price, Total Amount, Item Code).
- **Taxes**: Subtotal, Tax Rate(s), Total Tax Amount, Shipping/Handling, Grand Total, Currency.
- **Payment Information**: Bank Account, IBAN / Swift, Payment Method, Terms.
- **Notes / Metadata**: Vendor comments, return policy snippets.

#### 2. Onboarding / Registration Form Schema
- **Personal Information**: Full Name, Date of Birth, Gender, Nationality, Government ID / SSN / National ID.
- **Contact Information**: Residential Address, Email Address, Primary Phone, Alternative Phone.
- **Employment Information**: Position / Role, Department, Start Date, Employee ID, Employment Type.
- **Submitted Documents**: Checkboxes/flags for Photo ID, Address Proof, Tax Certificates, Signed Agreements.
- **Emergency Contact**: Name, Relationship, Phone Number, Secondary Contact.
- **Notes / Declarations**: Candidate sign-off, consent statements, HR reviewer remarks.

---

## 5. Database Architecture (Supabase PostgreSQL)

Persistence is managed in a normalized relational schema in Supabase PostgreSQL:

```sql
-- High-level Relational Schema

-- 1. Ingested Documents
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    storage_url TEXT,
    document_type TEXT, -- 'invoice' | 'onboarding' | 'unknown'
    status TEXT NOT NULL, -- 'uploaded' | 'processing' | 'completed' | 'failed'
    raw_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Document Sections
CREATE TABLE document_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    section_name TEXT NOT NULL,
    raw_content TEXT,
    bounding_box JSONB, -- spatial coordinates
    confidence NUMERIC(4, 3)
);

-- 3. Extracted Structured Data
CREATE TABLE field_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    field_key TEXT NOT NULL,
    field_value JSONB NOT NULL,
    confidence NUMERIC(4, 3),
    source_section TEXT
);

-- 4. Deterministic Validation Results
CREATE TABLE validation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    rule_name TEXT NOT NULL,
    status TEXT NOT NULL, -- 'passed' | 'warning' | 'failed'
    expected_value TEXT,
    actual_value TEXT,
    error_message TEXT
);

-- 5. Extracted Action Items
CREATE TABLE action_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    action_type TEXT NOT NULL, -- 'payment_approval' | 'missing_info' | 'compliance_check'
    priority TEXT NOT NULL, -- 'high' | 'medium' | 'low'
    due_date DATE,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'resolved' | 'dismissed'
    metadata JSONB
);
```

---

## 6. Document Processing Pipeline

The pipeline is organized into clear, sequential, and individually testable stages:

```
[ Upload ]
   │
   ▼
Stage 1: Preprocessing
   - File validation (MIME type, size limit).
   - Image format conversion, contrast adjustment, auto-orientation.
   │
   ▼
Stage 2: OCR & Layout Extraction
   - Extract raw text blocks, tokens, bounding boxes, and average OCR confidence.
   │
   ▼
Stage 3: Document Classification
   - Rule/keyword heuristic + light classifier identifies document archetype:
     • 'invoice'
     • 'onboarding'
   │
   ▼
Stage 4: Section Detection
   - Segmentation into contextual zones based on spatial layout and heading anchors.
   │
   ▼
Stage 5: Targeted Structured Extraction (Gemini)
   - Dispatches document-specific schema to Gemini client.
   - Outputs strictly typed JSON matching Pydantic contracts.
   │
   ▼
Stage 6: Normalization
   - Cleans formatting:
     • Dates -> ISO 8601 (YYYY-MM-DD).
     • Currencies -> Numeric floats + standard 3-letter currency code (e.g. USD, EUR, INR).
     • Phone numbers -> E.164 standardization.
   │
   ▼
Stage 7: Deterministic Validation
   - Pure Python rule execution:
     • Invoice: Subtotal + Taxes == Grand Total (within tolerance).
     • Invoice: Due Date >= Invoice Date.
     • Onboarding: Mandatory contact fields present and valid.
     • Onboarding: Emergency contact phone distinct from personal phone.
   │
   ▼
Stage 8: Summary & Action Extraction
   - Generates high-level 2-sentence executive summary from structured data.
   - Synthesizes prioritized, actionable operations.
   │
   ▼
Stage 9: Persistence & Delivery
   - Saves final state, validation logs, and actions to Supabase.
   - Pushes completed package to client response / dashboard.
```

---

## 7. Data Flow

```
[Client] ──> Multipart Upload (File) ──> [FastAPI /upload]
                                              │
                                              ▼
                                 [Pipeline Orchestrator]
                                              │
               ┌──────────────────────────────┼──────────────────────────────┐
               ▼                              ▼                              ▼
      [Preprocessor / OCR]          [Gemini Service]               [Validation Engine]
      Extracts Text + BBoxes        Extracts Typed JSON            Evaluates Rules
               │                              │                              │
               └──────────────────────────────┼──────────────────────────────┘
                                              │
                                              ▼
                                  [Normalized Pipeline Result]
                                              │
                                              ▼
                                  [Supabase Repository Layer]
                                              │
                                              ▼
[Client Dashboard] <─── JSON Response / Real-time Sync <─── [Supabase DB]
```

---

## 8. Future pgvector Integration

While pgvector is **explicitly excluded** from the core 24-hour MVP to avoid scope creep, the database schema and document service are designed with vector extensibility in mind:

- **Embeddings Table**: A future `document_embeddings` table storing vectors generated from normalized document summaries and line-item semantics:
  ```sql
  -- Future pgvector extension
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE TABLE document_embeddings (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
      embedding vector(768), -- Gemini embedding-001 dimension
      chunk_text TEXT
  );
  ```
- **Semantic Applications**:
  1. *Duplicate Invoice Detection*: Identify whether an identical or near-duplicate invoice has already been submitted under a different reference number.
  2. *Cross-Document Semantic Search*: Natural-language query interface across historical onboarding files and vendor contracts.
  3. *Vendor Pattern Matching*: Recognize recurring vendor layouts to optimize section detection over time.

---

## 9. Error Handling Strategy

To ensure hackathon stability and production robustness, error management follows five defensive layers:

1. **Upload / Ingestion Failures**:
   - Immediate HTTP 400/422 responses for unsupported MIME types, corrupted files, or payloads exceeding maximum file size limits (e.g. 15MB).
2. **OCR Degradation & Low Confidence**:
   - If OCR confidence drops below a defined threshold (e.g., 60%), mark the section with a `low_confidence` flag rather than failing the pipeline.
   - Future fallback: Trigger targeted multi-modal Gemini Vision specifically for low-confidence bounding boxes.
3. **AI Parsing & Schema Malformations**:
   - Guarded Gemini calls wrapped in exponential backoff retry logic.
   - Schema validation fallback: If Gemini returns malformed keys, Pydantic captures validation errors and falls back to a graceful partial extraction state without crashing the pipeline.
4. **Validation Non-Blocking Failures**:
   - Deterministic validation errors (such as math discrepancies on an invoice) are **recorded as actionable warnings/errors** in `validation_results`, NOT treated as pipeline crash exceptions. The user is alerted on the dashboard to inspect the discrepancy.
5. **Database Transaction Safeguards**:
   - Database operations use atomic commits or idempotent upserts keyed by `document_id`. If database persistence fails, the API returns the parsed in-memory result with a persistence warning flag so the user never loses their processed data.

---

## 10. 24-Hour MVP Scope

To guarantee successful, high-polish completion within a 24-hour hackathon timeframe, strict scope boundaries are established:

### In-Scope for 24-Hour MVP
- **Document Archetypes**: Strictly 2 types: Invoices/Bills and Onboarding Forms.
- **Core Processing Pipeline**: End-to-end flow from upload to OCR, classification, Gemini structured extraction, deterministic validation, and action derivation.
- **Single-Host Architecture**: Synchronous or lightweight FastAPI background task execution without Celery, Redis, or distributed message brokers.
- **UI Experience**: Polished, responsive React dashboard showing side-by-side document preview, parsed JSON / field cards, validation badges, and action checklist.
- **Reliable Persistence**: Core Supabase PostgreSQL tables storing processed documents, extraction results, and action items.

### Explicitly Out-of-Scope (Deferred to Post-Hackathon)
- User authentication and multi-tenant authorization.
- pgvector vector similarity queries and semantic search.
- Distributed task runners (Celery / Redis).
- Dockerized multi-container orchestration.
- Live automated accounting software integrations (QuickBooks, NetSuite, HRIS).
- Universal document parsing (arbitrary legal briefs, receipts, tax forms).
