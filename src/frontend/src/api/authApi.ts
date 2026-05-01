import { apiClient } from './axios';
import type { AuthResponse, AuthTokens, LoginPayload, RegisterPayload, User } from '@/types/auth';

export const loginApi = async (payload: LoginPayload): Promise<AuthResponse> => {
  const { data } = await apiClient.post<AuthResponse>('auth/login/', payload);
  return data;
};

export const registerApi = async (payload: RegisterPayload): Promise<AuthResponse> => {
  const { data } = await apiClient.post<AuthResponse>('auth/register/', payload);
  return data;
};

export const refreshTokenApi = async (refreshToken: string): Promise<AuthTokens> => {
  const { data } = await apiClient.post<AuthTokens>('auth/refresh/', { refreshToken });
  return data;
};

export const logoutApi = async (refreshToken: string): Promise<void> => {
  await apiClient.post('auth/logout/', { refreshToken });
};

export const getMeApi = async (): Promise<User> => {
  const { data } = await apiClient.get<User>('users/me/');
  return data;
};
