import axios from 'axios';

// Ensure baseURL has a trailing slash so axios resolves relative paths correctly.
// Django is sensitive to trailing slashes and expects URLs like /api/auth/login/.
const normalizeBaseUrl = (url: string): string => {
  return url.endsWith('/') ? url : `${url}/`;
};

const apiClient = axios.create({
  baseURL: normalizeBaseUrl(import.meta.env.VITE_API_URL ?? '/api'),
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: false,
});

// ── Request Interceptor: attach Bearer token ──────────────────────────
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// ── Token Refresh Queue ───────────────────────────────────────────────
let refreshPromise: Promise<boolean> | null = null;

const redirectToLogin = (): void => {
  if (
    !window.location.pathname.startsWith('/login') &&
    !window.location.pathname.startsWith('/register')
  ) {
    window.location.href = '/login';
  }
};

const refreshTokens = async (): Promise<boolean> => {
  const storedRefreshToken = localStorage.getItem('refresh_token');
  if (!storedRefreshToken) {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    redirectToLogin();
    return false;
  }

  try {
    const response = await axios.post(
      `${normalizeBaseUrl(import.meta.env.VITE_API_URL ?? '/api')}auth/refresh/`,
      { refreshToken: storedRefreshToken },
    );
    const { accessToken, refreshToken } = response.data;
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    return true;
  } catch {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    redirectToLogin();
    return false;
  }
};

// ── Response Interceptor: handle 401 with token refresh ───────────────
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Not a 401 → reject immediately
    if (!error.response || error.response.status !== 401) {
      return Promise.reject(error);
    }

    // Avoid infinite loop when /auth/refresh itself returns 401
    if (originalRequest.url?.includes('/auth/refresh')) {
      return Promise.reject(error);
    }

    // If no refresh is in progress, start one
    if (!refreshPromise) {
      refreshPromise = refreshTokens();
    }

    const refreshed = await refreshPromise;

    // Reset the promise so future 401s can trigger a new refresh
    refreshPromise = null;

    if (refreshed) {
      // Retry the original request with the new token
      const newToken = localStorage.getItem('access_token');
      originalRequest.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(originalRequest);
    }

    return Promise.reject(error);
  },
);

export { apiClient };
