import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Mock axios BEFORE importing the module under test ─────────────────
// AxiosInstance is callable (axios() is equivalent to axios.request()).
// Our mock must be a function that also has .interceptors, .defaults, etc.
const mockAxiosInstance = Object.assign(
  vi.fn(), // callable
  {
    interceptors: {
      request: { use: vi.fn(), handlers: [] as { fulfilled: Function; rejected: Function }[] },
      response: { use: vi.fn(), handlers: [] as { fulfilled: Function; rejected: Function }[] },
    },
    defaults: {} as Record<string, unknown>,
    post: vi.fn(),
    get: vi.fn(),
  },
);

// Track the registered interceptors
const requestHandlers: { fulfilled: Function; rejected: Function }[] = [];
const responseHandlers: { fulfilled: Function; rejected: Function }[] = [];

mockAxiosInstance.interceptors.request.use = vi.fn(
  (fulfilled: Function, rejected: Function) => {
    requestHandlers.push({ fulfilled, rejected });
    return 0;
  },
);

mockAxiosInstance.interceptors.response.use = vi.fn(
  (fulfilled: Function, rejected: Function) => {
    responseHandlers.push({ fulfilled, rejected });
    return 0;
  },
);

// Shared mock for axios.post — used by refreshTokens() in axios.ts
const mockPost = vi.fn();

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => mockAxiosInstance),
    post: mockPost,
  },
  create: vi.fn(() => mockAxiosInstance),
  post: mockPost,
}));

// ── Helpers ───────────────────────────────────────────────────────────
const createMockError = (status: number, url?: string) => {
  const error = new Error('Request failed') as Error & {
    config: { url?: string; headers?: Record<string, string> };
    response?: { status: number };
  };
  error.config = { url, headers: {} };
  if (status) {
    error.response = { status };
  }
  return error;
};

// ── Setup ─────────────────────────────────────────────────────────────
beforeEach(() => {
  // Clear registered handlers between tests
  requestHandlers.length = 0;
  responseHandlers.length = 0;

  // Reset mock calls
  vi.clearAllMocks();

  // Invalidate module cache so each test gets a fresh import
  vi.resetModules();

  // Stub localStorage
  const store: Record<string, string> = {};
  vi.stubGlobal(
    'localStorage',
    {
      getItem: vi.fn((key: string) => store[key] ?? null),
      setItem: vi.fn((key: string, value: string) => {
        store[key] = value;
      }),
      removeItem: vi.fn((key: string) => {
        delete store[key];
      }),
      clear: vi.fn(() => {
        Object.keys(store).forEach((k) => delete store[k]);
      }),
      get length() {
        return Object.keys(store).length;
      },
      key: vi.fn((index: number) => Object.keys(store)[index] ?? null),
    } as Storage,
  );

  // Stub window.location — make href writable
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).location;
  window.location = { href: '', pathname: '' } as unknown as Location;
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ── Tests ─────────────────────────────────────────────────────────────
describe('Axios request interceptor', () => {
  it('attaches Bearer token when token exists in localStorage', async () => {
    localStorage.setItem('access_token', 'test-token-123');

    // Import triggers module init which registers interceptors
    await import('../../src/api/axios');

    const config = await requestHandlers[0].fulfilled({
      headers: {} as Record<string, string>,
      url: '/users/me',
    });

    expect(config.headers.Authorization).toBe('Bearer test-token-123');
  });

  it('does NOT attach token when no token in localStorage', async () => {
    localStorage.removeItem('access_token');

    await import('../../src/api/axios');

    const config = await requestHandlers[0].fulfilled({
      headers: {} as Record<string, string>,
      url: '/auth/login',
    });

    expect(config.headers.Authorization).toBeUndefined();
  });
});

describe('Axios response interceptor — 401 handling', () => {
  beforeEach(() => {
    localStorage.setItem('access_token', 'expired-token');
    localStorage.setItem('refresh_token', 'valid-refresh-token');
  });

  it('on 401, calls /auth/refresh and retries the original request', async () => {
    // Mock the POST for /auth/refresh to succeed
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const axios = (await import('axios')) as any;
    axios.post.mockResolvedValueOnce({
      data: {
        accessToken: 'new-access-token',
        refreshToken: 'new-refresh-token',
      },
    });

    await import('../../src/api/axios');

    const error = createMockError(401, '/users/me');

    // The retry calls apiClient(originalRequest) — make it return something
    mockAxiosInstance.mockResolvedValue({ data: 'retried' });

    const result = await responseHandlers[0].rejected(error);

    // Should have called /auth/refresh
    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining('/auth/refresh'),
      { refreshToken: 'valid-refresh-token' },
    );

    // Should have saved new tokens
    expect(localStorage.getItem('access_token')).toBe('new-access-token');
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh-token');

    // Should have retried the original request
    expect(result).toBeDefined();
  });

  it('queue mechanism — 3 concurrent 401s trigger only 1 refresh call', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const axios = (await import('axios')) as any;
    axios.post.mockResolvedValue({
      data: {
        accessToken: 'new-access-token',
        refreshToken: 'new-refresh-token',
      },
    });

    await import('../../src/api/axios');

    const error = createMockError(401, '/users/me');

    // Fire 3 concurrent 401 errors
    await Promise.allSettled([
      responseHandlers[0].rejected(error),
      responseHandlers[0].rejected(error),
      responseHandlers[0].rejected(error),
    ]);

    // axios.post should have been called only once for /auth/refresh
    const refreshCalls = axios.post.mock.calls.filter(
      ([url]: [string]) => typeof url === 'string' && url.includes('/auth/refresh'),
    );
    expect(refreshCalls.length).toBe(1);
  });

  it('on refresh failure, clears localStorage and redirects to /login', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const axios = (await import('axios')) as any;
    axios.post.mockRejectedValueOnce(new Error('Refresh failed'));

    await import('../../src/api/axios');

    const error = createMockError(401, '/users/me');

    await expect(
      responseHandlers[0].rejected(error),
    ).rejects.toThrow();

    // localStorage should be cleared
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();

    // Should redirect to /login
    expect(window.location.href).toBe('/login');
  });

  it('does NOT retry if failed request is to /auth/refresh itself', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const axios = (await import('axios')) as any;

    await import('../../src/api/axios');

    const error = createMockError(401, '/auth/refresh');

    await expect(
      responseHandlers[0].rejected(error),
    ).rejects.toThrow();

    // Should NOT have called /auth/refresh again
    expect(axios.post).not.toHaveBeenCalled();
  });
});
