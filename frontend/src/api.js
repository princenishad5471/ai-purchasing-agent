const API_BASE = '/api';

export const api = {
  async createRecommendation(data) {
    const response = await fetch(`${API_BASE}/recommendations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error('Failed to create recommendation');
    return response.json();
  },

  async reviewRecommendation(recommendationId) {
    const response = await fetch(`${API_BASE}/recommendations/${recommendationId}/review`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to review recommendation');
    return response.json();
  },

  async getRecommendation(recommendationId) {
    const response = await fetch(`${API_BASE}/recommendations/${recommendationId}`);
    if (!response.ok) throw new Error('Failed to get recommendation');
    return response.json();
  },

  async healthCheck() {
    const response = await fetch(`${API_BASE}/health`);
    if (!response.ok) throw new Error('Health check failed');
    return response.json();
  },
};
