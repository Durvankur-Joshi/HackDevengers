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
}

export const api = new ApiService();
