# Supabase Project Setup Guide

This guide outlines the one-time configuration required in your Supabase project for the **Document-to-Action Pipeline**.

---

## 1. Database Schema Execution

1. Open your [Supabase Dashboard](https://supabase.com/dashboard).
2. Select your project.
3. In the left navigation bar, click on **SQL Editor**.
4. Click **New query**.
5. Paste the entire contents of [`docs/database.sql`](./database.sql).
6. Click **Run** (or `Ctrl + Enter`).
7. Confirm that the query succeeds. The following 5 tables will be active:
   - `documents` (with `storage_path`)
   - `document_sections`
   - `extracted_fields`
   - `actions`
   - `processing_logs`

---

## 2. Supabase Storage Bucket Setup

1. In the left navigation bar of your Supabase Dashboard, click on **Storage**.
2. Click **New bucket**.
3. Set the **Bucket name** to:
   ```text
   documents
   ```
4. **Public bucket**: Leave **unchecked** (private bucket) for secure signed-URL access, or public if preferred for local development.
5. Click **Save bucket**.

### Storage Policies (If bucket is private):
If Row Level Security (RLS) is enabled for Storage, add a policy to permit uploads:
- **Allow authenticated / anon uploads**:
  - In Storage → `documents` bucket → **Configuration** → **Policies**.
  - Click **New Policy** → **For full customization**.
  - Name: `Allow public or anon uploads`
  - Target roles: `anon`, `authenticated`
  - Allowed operations: `SELECT`, `INSERT`, `UPDATE`, `DELETE`
  - Review and save.

---

## 3. Environment Variables Configuration

In `backend/.env`, verify that your project credentials are set:
```ini
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-or-service-key
```

Then run the database connectivity verification test:
```powershell
e:\HackDevengers\backend\.venv\Scripts\python.exe app/services/verify_db.py
```
