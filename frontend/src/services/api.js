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

  /**
   * Execute layout-aware OCR extraction stage
   * @param {string} documentId
   */
  async runOcr(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/ocr`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'OCR extraction failed.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error during OCR extraction.' };
    }
  }

  /**
   * Fetch structured OCR result artifact for an existing document
   * @param {string} documentId
   */
  async getOcr(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/ocr`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Could not load OCR results.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error retrieving OCR results.' };
    }
  }

  /**
   * Execute semantic document classification stage via Gemini
   * @param {string} documentId
   */
  async classifyDocument(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/classify`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Classification failed.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error during document classification.' };
    }
  }

  /**
   * Retrieve cached classification result for an existing document
   * @param {string} documentId
   */
  async getClassification(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/classification`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Could not load classification.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error retrieving classification.' };
    }
  }

  /**
   * Execute Phase 7 logical section detection via Gemini
   * @param {string} documentId
   */
  async detectSections(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/detect-sections`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Section detection failed.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error during section detection.' };
    }
  }

  /**
   * Retrieve cached section detection results for an existing document
   * @param {string} documentId
   */
  async getSections(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/sections`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Could not load sections.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error retrieving sections.' };
    }
  }

  /**
   * Execute Phase 8 targeted structured AI extraction via Gemini
   * @param {string} documentId
   */
  async extractFields(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/extract`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Field extraction failed.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error during structured extraction.' };
    }
  }

  /**
   * Retrieve cached extraction results for an existing document
   * @param {string} documentId
   */
  async getExtraction(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/extraction`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Could not load extraction results.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error retrieving extraction results.' };
    }
  }

  /**
   * Execute Phase 9 deterministic normalization and validation
   * @param {string} documentId
   */
  async validateDocument(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/validate`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Validation failed.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error during validation.' };
    }
  }

  /**
   * Retrieve cached validation results for an existing document
   * @param {string} documentId
   */
  async getValidation(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/validation`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Could not load validation results.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error retrieving validation results.' };
    }
  }

  /**
   * Execute Phase 10 Low-Confidence & Handwriting Vision Fallback
   * @param {string} documentId
   */
  async runVisionFallback(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/vision-fallback`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Vision fallback failed.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error during vision fallback.' };
    }
  }

  /**
   * Retrieve cached vision fallback results for an existing document
   * @param {string} documentId
   */
  async getVisionFallback(documentId) {
    try {
      const response = await fetch(`${this.baseUrl}/api/documents/${documentId}/vision-fallback`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        return { ok: false, error: data?.detail || 'Could not load vision fallback results.' };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: err.message || 'Network error retrieving vision fallback results.' };
    }
  }
}

export const api = new ApiService();

