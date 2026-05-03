// ── Mock authApi BEFORE importing the store ────────────────────────────
vi.mock('@/api/authApi', () => ({
  loginApi: vi.fn(),
  registerApi: vi.fn(),
  logoutApi: vi.fn(),
  getMeApi: vi.fn(),
}));

// ── Mock data ──────────────────────────────────────────────────────────
const mockUser = {
  id: 'user-1',
  email: 'test@example.com',
  full_name: 'Test User',
  is_active: true,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
};

const mockLoginPayload = {
  email: 'test@example.com',
  password: 'password123',
};

const mockRegisterPayload = {
  email: 'test@example.com',
  password: 'password123',
  full_name: 'Test User',
};

const mockAuthResponse = {
  user: mockUser,
  accessToken: 'access-token-123',
  refreshToken: 'refresh-token-456',
};

// ── Setup ──────────────────────────────────────────────────────────────
beforeEach(() => {
  vi.clearAllMocks();
  vi.resetModules();
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Helper to get a fresh store ────────────────────────────────────────
async function resetStore() {
  const { useAuthStore } = await import('@/stores/authStore');
  useAuthStore.setState({
    user: null,
    isAuthenticated: false,
    isLoading: false,
  });
  return useAuthStore;
}

// ── Tests ──────────────────────────────────────────────────────────────
describe('AuthStore', () => {
  describe('login', () => {
    it('calls loginApi, saves tokens, and updates state on success', async () => {
      const authApi = await import('@/api/authApi');
      vi.mocked(authApi.loginApi).mockResolvedValue(mockAuthResponse);

      const setItemSpy = vi.spyOn(Storage.prototype, 'setItem');
      const useAuthStore = await resetStore();

      await useAuthStore.getState().login(mockLoginPayload);

      expect(authApi.loginApi).toHaveBeenCalledWith(mockLoginPayload);
      expect(setItemSpy).toHaveBeenCalledWith('access_token', 'access-token-123');
      expect(setItemSpy).toHaveBeenCalledWith('refresh_token', 'refresh-token-456');

      const state = useAuthStore.getState();
      expect(state.user).toEqual(mockUser);
      expect(state.isAuthenticated).toBe(true);
    });

    it('propagates API error and does not update state', async () => {
      const authApi = await import('@/api/authApi');
      vi.mocked(authApi.loginApi).mockRejectedValue(new Error('Invalid credentials'));

      const useAuthStore = await resetStore();

      await expect(
        useAuthStore.getState().login(mockLoginPayload),
      ).rejects.toThrow('Invalid credentials');

      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe('register', () => {
    it('calls registerApi, saves tokens, and updates state on success', async () => {
      const authApi = await import('@/api/authApi');
      vi.mocked(authApi.registerApi).mockResolvedValue(mockAuthResponse);

      const setItemSpy = vi.spyOn(Storage.prototype, 'setItem');
      const useAuthStore = await resetStore();

      await useAuthStore.getState().register(mockRegisterPayload);

      expect(authApi.registerApi).toHaveBeenCalledWith(mockRegisterPayload);
      expect(setItemSpy).toHaveBeenCalledWith('access_token', 'access-token-123');
      expect(setItemSpy).toHaveBeenCalledWith('refresh_token', 'refresh-token-456');

      const state = useAuthStore.getState();
      expect(state.user).toEqual(mockUser);
      expect(state.isAuthenticated).toBe(true);
    });

    it('propagates API error and does not update state', async () => {
      const authApi = await import('@/api/authApi');
      vi.mocked(authApi.registerApi).mockRejectedValue(new Error('Email already exists'));

      const useAuthStore = await resetStore();

      await expect(
        useAuthStore.getState().register(mockRegisterPayload),
      ).rejects.toThrow('Email already exists');

      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe('logout', () => {
    it('calls logoutApi with refresh token then clears auth', async () => {
      const authApi = await import('@/api/authApi');
      vi.mocked(authApi.logoutApi).mockResolvedValue(undefined);

      const removeItemSpy = vi.spyOn(Storage.prototype, 'removeItem');
      const useAuthStore = await resetStore();

      localStorage.setItem('access_token', 'access-token-123');
      localStorage.setItem('refresh_token', 'refresh-token-456');
      useAuthStore.setState({ user: mockUser, isAuthenticated: true, isLoading: false });

      await useAuthStore.getState().logout();

      expect(authApi.logoutApi).toHaveBeenCalledWith('refresh-token-456');
      expect(removeItemSpy).toHaveBeenCalledWith('access_token');
      expect(removeItemSpy).toHaveBeenCalledWith('refresh_token');

      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });

    it('clears auth even if logoutApi fails', async () => {
      const authApi = await import('@/api/authApi');
      vi.mocked(authApi.logoutApi).mockRejectedValue(new Error('Network error'));

      const removeItemSpy = vi.spyOn(Storage.prototype, 'removeItem');
      const useAuthStore = await resetStore();

      localStorage.setItem('access_token', 'access-token-123');
      localStorage.setItem('refresh_token', 'refresh-token-456');
      useAuthStore.setState({ user: mockUser, isAuthenticated: true, isLoading: false });

      await expect(
        useAuthStore.getState().logout(),
      ).resolves.toBeUndefined();

      expect(removeItemSpy).toHaveBeenCalledWith('access_token');
      expect(removeItemSpy).toHaveBeenCalledWith('refresh_token');

      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe('clearAuth', () => {
    it('removes tokens from localStorage and resets state', async () => {
      const removeItemSpy = vi.spyOn(Storage.prototype, 'removeItem');
      const useAuthStore = await resetStore();

      localStorage.setItem('access_token', 'access-token-123');
      localStorage.setItem('refresh_token', 'refresh-token-456');
      useAuthStore.setState({ user: mockUser, isAuthenticated: true, isLoading: false });

      useAuthStore.getState().clearAuth();

      expect(removeItemSpy).toHaveBeenCalledWith('access_token');
      expect(removeItemSpy).toHaveBeenCalledWith('refresh_token');

      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
      expect(state.isLoading).toBe(false);
    });
  });

  describe('initializeAuth', () => {
    it('on success, sets user and isAuthenticated, clears loading', async () => {
      const authApi = await import('@/api/authApi');
      vi.mocked(authApi.getMeApi).mockResolvedValue(mockUser);

      const useAuthStore = await resetStore();

      localStorage.setItem('access_token', 'valid-token');

      await useAuthStore.getState().initializeAuth();

      expect(authApi.getMeApi).toHaveBeenCalled();

      const state = useAuthStore.getState();
      expect(state.user).toEqual(mockUser);
      expect(state.isAuthenticated).toBe(true);
      expect(state.isLoading).toBe(false);
    });

    it('on failure, clears auth and stops loading', async () => {
      const authApi = await import('@/api/authApi');
      vi.mocked(authApi.getMeApi).mockRejectedValue(new Error('Token expired'));

      const useAuthStore = await resetStore();

      await useAuthStore.getState().initializeAuth();

      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
      expect(state.isLoading).toBe(false);
    });
  });

  describe('setUser', () => {
    it('updates the user in store state', async () => {
      const useAuthStore = await resetStore();

      useAuthStore.getState().setUser(mockUser);

      const state = useAuthStore.getState();
      expect(state.user).toEqual(mockUser);
    });
  });
});
