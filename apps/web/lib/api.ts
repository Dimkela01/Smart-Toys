/**
 * Thin API client.
 *
 * Everything goes to the same origin (see next.config.ts rewrites), so the httpOnly
 * refresh cookie travels with the request and no CORS or token storage is involved for it.
 */

export const API = '/api/v1';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

type Json = Record<string, unknown> | unknown[];

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: Json;
  token?: string | null;
  signal?: AbortSignal;
}

interface ErrorDetail {
  code?: unknown;
  message?: unknown;
}

function readError(status: number, payload: unknown): ApiError {
  const detail = (payload as { detail?: unknown } | null)?.detail;

  // our own errors: {"detail": {"code": ..., "message": ...}}
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const { code, message } = detail as ErrorDetail;
    return new ApiError(
      status,
      typeof code === 'string' ? code : 'error',
      typeof message === 'string' ? message : '',
    );
  }

  // FastAPI validation errors arrive as a list
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown } | undefined;
    return new ApiError(
      status,
      'validation_error',
      typeof first?.msg === 'string' ? first.msg : '',
    );
  }

  return new ApiError(status, 'error', '');
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, token, signal } = options;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
    signal,
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) throw readError(response.status, payload);
  return payload as T;
}

/* --- shapes returned by the API (ARCHITECTURE.md §7.1) --- */

export interface Parent {
  id: string;
  email: string;
  locale: string;
  email_verified: boolean;
  pin_set: boolean;
}

export type Requirement = 'email_verification' | 'pin';

export interface SessionResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  parent: Parent;
  requires: Requirement[];
}

export interface MeResponse {
  parent: Parent;
  requires: Requirement[];
}

export interface ChildSettings {
  activities_enabled: Record<string, boolean>;
  blocked_topics: string[];
  daily_limit_min: number;
  allowed_from: string;
  allowed_to: string;
  memory_enabled: boolean;
  transcripts_visible: boolean;
  alerts_email: boolean;
}

export interface Child {
  id: string;
  nickname: string;
  age: number;
  language: 'sr' | 'en';
  interests: string[];
  avatar_id: string;
  character_id: string;
  first_session_done: boolean;
  created_at: string;
  settings: ChildSettings;
}

export interface Avatar {
  id: string;
  asset: string;
  color: string | null;
  label: Record<string, string>;
}

export interface Character {
  id: string;
  name: Record<string, string>;
  asset: string;
  sample: string | null;
}

export interface Catalog {
  avatars: Avatar[];
  characters: Character[];
  interest_suggestions: string[];
  languages: ('sr' | 'en')[];
  limits: {
    max_children: number;
    max_interests: number;
    nickname_max_length: number;
    age_min: number;
    age_max: number;
  };
  consent_version: string;
}

export interface ChildPicker {
  id: string;
  nickname: string;
  avatar_id: string;
}

export interface EnterChildModeResponse {
  token: string;
  expires_in: number;
  children: ChildPicker[];
}

export interface ChildToy {
  id: string;
  nickname: string;
  language: 'sr' | 'en';
  character_id: string;
  avatar_id: string;
  activities_enabled: Record<string, boolean>;
  first_session_done: boolean;
}

export interface SelectChildResponse {
  token: string;
  expires_in: number;
  child: ChildToy;
}

export interface AdminAccount {
  id: string;
  email: string;
  role: string;
}

export interface AdminSessionResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  admin: AdminAccount;
}

export const catalog = () => request<Catalog>('/meta/catalog');
