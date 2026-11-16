'use client';

/**
 * Parent session.
 *
 * The access token lives in memory only: never in localStorage, where any script could
 * read it. Continuity across reloads comes from the httpOnly refresh cookie, which the
 * browser sends to /api/v1/auth on the same origin.
 *
 * While a device is locked in child mode the server refuses to refresh
 * (403 child_mode_active), so a reload lands on the child screen rather than handing a
 * parent session back without the PIN (UC-05 AC, UC-21).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  ApiError,
  request,
  type MeResponse,
  type Parent,
  type Requirement,
  type RequestOptions,
  type SessionResponse,
} from '@/lib/api';
import { deviceId } from '@/lib/device';
import { DEFAULT_LOCALE, isLocale, LocaleProvider, type Locale } from '@/lib/i18n';

export type SessionStatus = 'loading' | 'anonymous' | 'child_mode' | 'signed_in';

interface SessionValue {
  status: SessionStatus;
  parent: Parent | null;
  requires: Requirement[];
  /** Authenticated request; refreshes once and retries on an expired access token. */
  call: <T>(path: string, options?: RequestOptions) => Promise<T>;
  login: (email: string, password: string) => Promise<SessionResponse>;
  adopt: (session: SessionResponse) => void;
  /** Apply an account state returned by /auth/me or /auth/pin. */
  applyMe: (me: MeResponse) => void;
  refresh: () => Promise<boolean>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }): ReactNode {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [parent, setParent] = useState<Parent | null>(null);
  const [requires, setRequires] = useState<Requirement[]>([]);
  const token = useRef<string | null>(null);

  const adopt = useCallback((session: SessionResponse) => {
    token.current = session.access_token;
    setParent(session.parent);
    setRequires(session.requires);
    setStatus('signed_in');
  }, []);

  const applyMe = useCallback((me: MeResponse) => {
    setParent(me.parent);
    setRequires(me.requires);
  }, []);

  const forget = useCallback(() => {
    token.current = null;
    setParent(null);
    setRequires([]);
  }, []);

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const session = await request<SessionResponse>('/auth/refresh', { method: 'POST' });
      adopt(session);
      return true;
    } catch (error) {
      forget();
      // the device is locked in child mode; only the PIN gets the parent back
      setStatus(
        error instanceof ApiError && error.code === 'child_mode_active'
          ? 'child_mode'
          : 'anonymous',
      );
      return false;
    }
  }, [adopt, forget]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const call = useCallback(
    async <T,>(path: string, options: RequestOptions = {}): Promise<T> => {
      try {
        return await request<T>(path, { ...options, token: token.current });
      } catch (error) {
        const expired =
          error instanceof ApiError &&
          error.status === 401 &&
          ['token_expired', 'not_authenticated', 'invalid_token'].includes(error.code);
        if (!expired) throw error;
        if (!(await refresh())) throw error;
        return await request<T>(path, { ...options, token: token.current });
      }
    },
    [refresh],
  );

  const login = useCallback(
    async (email: string, password: string): Promise<SessionResponse> => {
      const session = await request<SessionResponse>('/auth/login', {
        method: 'POST',
        body: { email, password, device_id: deviceId() },
      });
      adopt(session);
      return session;
    },
    [adopt],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await request('/auth/logout', { method: 'POST' });
    } finally {
      forget();
      setStatus('anonymous');
    }
  }, [forget]);

  // keep `requires` honest after the PIN or verification step
  useEffect(() => {
    if (status !== 'signed_in' || requires.length === 0) return;
    let cancelled = false;
    void (async () => {
      try {
        const me = await call<MeResponse>('/auth/me');
        if (!cancelled) applyMe(me);
      } catch {
        // handled on the next interaction
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, requires.length, call, applyMe]);

  const value = useMemo<SessionValue>(
    () => ({ status, parent, requires, call, login, adopt, applyMe, refresh, logout }),
    [status, parent, requires, call, login, adopt, applyMe, refresh, logout],
  );

  const locale: Locale = isLocale(parent?.locale) ? parent.locale : DEFAULT_LOCALE;

  return (
    <SessionContext.Provider value={value}>
      <LocaleProvider locale={locale}>{children}</LocaleProvider>
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (value === null) throw new Error('useSession must be used inside SessionProvider');
  return value;
}
