// src/api/auth.ts

import { api, setAuthToken } from "./client";

type TokenResponse = { access_token: string };
type SignupRequest = { email: string; password: string; display_name?: string };
type LoginRequest = { email: string; password: string };
type UserProfile = {
  id: string;
  email: string;
  display_name?: string | null;
  created_at?: string | null;
  last_login_at?: string | null;
};

export async function signup(data: SignupRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>("/auth/signup", data);
  setAuthToken(res.data.access_token);
  return res.data;
}

export async function login(data: LoginRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>("/auth/login", data);
  setAuthToken(res.data.access_token);
  return res.data;
}

export async function me(): Promise<UserProfile> {
  const res = await api.get<UserProfile>("/auth/me");
  return res.data;
}

export function logout() {
  setAuthToken(null);
}
