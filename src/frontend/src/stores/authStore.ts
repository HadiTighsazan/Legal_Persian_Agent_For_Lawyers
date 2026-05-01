import { create } from 'zustand';
import { loginApi, registerApi, logoutApi, getMeApi } from '@/api/authApi';
import type { User, LoginPayload, RegisterPayload } from '@/types/auth';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthActions {
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  initializeAuth: () => Promise<void>;
  setUser: (user: User) => void;
  clearAuth: () => void;
}

type AuthStore = AuthState & AuthActions;

const initialState: AuthState = {
  user: null,
  isAuthenticated: false,
  isLoading: false,
};

export const useAuthStore = create<AuthStore>((set) => ({
  ...initialState,

  login: async (payload: LoginPayload): Promise<void> => {
    const { user, accessToken, refreshToken } = await loginApi(payload);
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    set({ user, isAuthenticated: true });
  },

  register: async (payload: RegisterPayload): Promise<void> => {
    const { user, accessToken, refreshToken } = await registerApi(payload);
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    set({ user, isAuthenticated: true });
  },

  logout: async (): Promise<void> => {
    const refreshToken = localStorage.getItem('refresh_token');
    try {
      if (refreshToken) {
        await logoutApi(refreshToken);
      }
    } catch {
      // Swallow errors — logout should proceed even if API fails
    } finally {
      const store = useAuthStore.getState();
      store.clearAuth();
    }
  },

  clearAuth: (): void => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    set({ ...initialState });
  },

  initializeAuth: async (): Promise<void> => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      set({ isLoading: false });
      return;
    }
    set({ isLoading: true });
    try {
      const user = await getMeApi();
      set({ user, isAuthenticated: true, isLoading: false });
    } catch {
      const store = useAuthStore.getState();
      store.clearAuth();
      set({ isLoading: false });
    }
  },

  setUser: (user: User): void => {
    set({ user });
  },
}));
