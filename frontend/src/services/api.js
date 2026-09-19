/**
 * Minimal API service abstraction for Document-to-Action Pipeline
 * Configured with environment variable VITE_API_BASE_URL
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export class ApiService {
  constructor(baseUrl = API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  getBaseUrl() {
    return this.baseUrl;
  }

  /**
   * Health check endpoint to verify backend service status
   * @returns {Promise<{ ok: boolean, status: string, latencyMs?: number, raw?: any, error?: string }>}
   */
  async checkHealth() {
    const start = performance.now();
    try {
      const response = await fetch(`${this.baseUrl}/health`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
        },
      });

      const latencyMs = Math.round(performance.now() - start);

      if (!response.ok) {
        return {
          ok: false,
          status: 'Disconnected',
          latencyMs,
          error: `HTTP ${response.status}: ${response.statusText}`,
        };
      }

      const data = await response.json();
      return {
        ok: data.status === 'ok',
        status: data.status === 'ok' ? 'Connected' : 'Degraded',
        latencyMs,
        raw: data,
      };
    } catch (err) {
      const latencyMs = Math.round(performance.now() - start);
      return {
        ok: false,
        status: 'Disconnected',
        latencyMs,
        error: err.message || 'Failed to reach backend server',
      };
    }
  }

  /**
   * Fetch system root metadata if available
   */
  async getSystemInfo() {
    try {
      const response = await fetch(`${this.baseUrl}/`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
        },
      });
      if (response.ok) {
        return await response.json();
      }
      return null;
    } catch {
      return null;
    }
  }

  /**
   * Ingest a document via multipart/form-data
   * @param {File} file - The selected file
   * @returns {Promise<{ ok: boolean, data?: any, error?: string }>}
   */
  async uploadDocument(file) {
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${this.baseUrl}/api/documents/upload`, {
        method: 'POST',
        body: formData,
      });

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        const errorMsg = data?.detail || `Upload failed with HTTP ${response.status}`;
        return { ok: false, error: errorMsg };
      }

      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error during document upload.' };
    }
  }

  /**
   * Fetch metadata of an uploaded document
   * @param {string} documentId
   */
  async getDocument(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Document not found.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error retrieving document.' };
    }
  }

  /**
   * Fetch signed temporary preview URL for an uploaded document
   * @param {string} documentId
   */
  async getDocumentPreview(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/preview`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Could not load preview.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error retrieving preview.' };
    }
  }

  /**
   * Trigger document preprocessing stage (converts pages to OCR-ready format)
   * @param {string} documentId
   */
  async preprocessDocument(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/preprocess`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Preprocessing failed.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error during preprocessing.' };
    }
  }
}

export const api = new ApiService();
