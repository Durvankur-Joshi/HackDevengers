# Document-to-Action Pipeline

An AI-powered document intelligence system designed to transform messy real-world documents—such as scanned invoices, paper receipts, and onboarding registration forms—into clean, validated, and structured actionable data. By pairing classical document preprocessing and layout/OCR extraction with targeted Google Gemini structured extraction, deterministic validation, and operational action triggers, the pipeline bridges the gap between unstructured physical records and modern software workflows without naive end-to-end LLM dependencies.

---

## The Problem

Organizations and teams are flooded with physical, scanned, and digital documents like vendor invoices and employee onboarding forms. Traditional data entry is slow, expensive, and error-prone. Conversely, naive modern AI solutions often rely on an "upload document → send whole file to LLM → pray for JSON" pattern. This approach suffers from critical flaws:
- **Hallucinations & Missing Data**: LLMs miss small text, misread blurry numbers, or fabricate missing fields without grounding.
- **Cost & Latency**: Sending raw multi-page high-resolution files straight to multi-modal models incurs excessive latency and token costs.
- **Lack of Provenance & Verification**: Pure generative outputs lack field-level confidence scores, bounding boxes, or verifiable line-item arithmetic validation.
- **Lack of Actionability**: Extracting raw text is useless if downstream operational tasks (e.g., payment scheduling, profile creation, compliance checklists) are not synthesized.

---

## The Solution

The **Document-to-Action Pipeline** decouples ingestion, text/layout extraction, semantic understanding, validation, and action triggering into a modular, observable architecture:
1. **Deterministic Preprocessing & OCR**: Extracts raw text tokens, spatial bounding coordinates, and confidence metadata locally before involving language models.
2. **Targeted Section Extraction with Gemini**: Passes layout-aware sections to Google Gemini using strict Pydantic schemas, constraining the model to high-value contextual structuring.
3. **Independent Rule-Based Validation**: Runs deterministic business logic (e.g., line-item sum reconciliation, tax rate checks, mandatory field audits) outside the LLM.
4. **Action Extraction**: Derives actionable next steps (payment approvals, missing document alerts, system integrations) directly from validated data structures.
5. **Persistence & UI Visibility**: Persists records into Supabase PostgreSQL and displays them on a clean, real-time React dashboard with audit trails.

---

## Tech Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Frontend** | React, Vite, Tailwind CSS, shadcn/ui | High-performance interactive dashboard, document inspection, validation reporting |
| **Backend** | Python, FastAPI | High-throughput async REST API, pipeline orchestration, modular service boundaries |
| **AI / Intelligence** | Google Gemini API | Layout-guided structured extraction, concise summarization, and action item synthesis |
| **Database** | Supabase (PostgreSQL) | Relational persistence of documents, parsed fields, validation errors, and action items |
| **Vector Search** *(Optional)* | Supabase pgvector | *(Future enhancement)* Semantic similarity, duplicate detection, and document querying |

---

## High-Level Pipeline

```
Document Upload
      ↓
Preprocessing (Image enhancement, orientation, cleanup)
      ↓
OCR & Layout Extraction (Text tokens, bounding boxes, confidence)
      ↓
Document Classification (Invoice / Bill vs. Onboarding Form)
      ↓
Section Detection (Segment document into logical functional zones)
      ↓
Targeted Structured Extraction (Gemini with typed schemas)
      ↓
Normalization (Dates to ISO 8601, currency to standard floats, clean strings)
      ↓
Deterministic Validation (Arithmetic checks, required fields, date logic)
      ↓
Summary Generation (Concise natural-language executive overview)
      ↓
Action Extraction (Operational next steps, flags, approval requirements)
      ↓
Supabase Persistence (Relational storage with audit trail)
      ↓
React Dashboard (Real-time review, validation alerts, action tracking)
```

---

## MVP Scope (24-Hour Hackathon)

The initial MVP targets two high-impact document archetypes, maintaining extreme modularity and strict service separation:

### 1. Supported Document Types
1. **Invoice / Bill**:
   - *Expected Sections*: Vendor Information, Customer Information, Invoice Details, Line Items, Taxes, Payment Information, Notes.
   - *Key Actions*: Payment approval triggers, due date alerts, bank routing validation.
2. **Onboarding / Registration Form**:
   - *Expected Sections*: Personal Information, Contact Information, Employment Information, Submitted Documents, Emergency Contact, Notes.
   - *Key Actions*: Missing document checklists, HR verification tasks, emergency contact completeness flags.

### 2. Core Capabilities
- Single-document upload interface (PDF / image).
- Local layout and text extraction with confidence scoring.
- Modular Gemini service layer executing structured JSON extraction via typed schemas.
- Deterministic validation suite running independently of AI calls.
- Automated generation of structured executive summaries and prioritized action items.
- Persisted state in Supabase PostgreSQL displayed via a responsive React dashboard.

---

## Future Scope

- **Targeted Vision Fallback**: Automatically trigger multi-modal Gemini Vision passes selectively on low-confidence OCR bounding boxes or handwritten signatures.
- **Semantic Search (pgvector)**: Enable vector embeddings on extracted document entities to detect duplicate invoices, query past registrations, and match vendor patterns.
- **Expanded Document Library**: Add automated support for medical intake forms, tax filings (W-2 / 1099), and receipts.
- **Asynchronous Task Queue**: Introduce background worker queues (Celery / Redis / background workers) for distributed batch document ingestion.
- **Human-in-the-Loop (HITL) Review**: Interactive field correction editor on the frontend that records provenance and feeds correction logs into prompt optimization.
