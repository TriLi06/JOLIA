import axios from 'axios';

const api = axios.create({
  baseURL: (import.meta as any).env?.VITE_API_BASE_URL ?? '/api',
  timeout: 30000,
  headers: {
    Accept: 'application/json',
  },
});

// Fehler im Entwicklungsmodus protokollieren
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if ((import.meta as any).env?.DEV) {
      console.error('[API-Fehler]', error.config?.url, error.message, error.response?.data);
    }
    return Promise.reject(error);
  },
);

export default api;
