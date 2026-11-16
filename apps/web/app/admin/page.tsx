'use client';

/**
 * Admin sign-in and an empty layout (M1 checklist).
 *
 * The model and prompt registry, evaluation runs, the metrics dashboard and the rating
 * queue are M6. Metrics and model names are never shown outside these pages
 * (docs/CLAUDE.md §2).
 */

import { useState, type ReactNode } from 'react';
import { Button, Field, Input, Notice } from '@/components/ui';
import { ApiError, request, type AdminAccount, type AdminSessionResponse } from '@/lib/api';
import { useT } from '@/lib/i18n';

export default function AdminPage(): ReactNode {
  const t = useT();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [admin, setAdmin] = useState<AdminAccount | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const session = await request<AdminSessionResponse>('/admin/login', {
        method: 'POST',
        body: { email, password, totp_code: code },
      });
      setAdmin(session.admin);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'account_locked') {
        setError(t('admin.accountLocked'));
      } else if (caught instanceof ApiError && caught.code === 'rate_limited') {
        setError(t('common.rateLimited'));
      } else if (caught instanceof ApiError && caught.status === 401) {
        setError(t('admin.invalidCredentials'));
      } else if (caught instanceof ApiError && caught.status === 422) {
        setError(t('admin.invalidCredentials'));
      } else {
        setError(t('common.errorGeneric'));
      }
    } finally {
      setBusy(false);
      setCode('');
    }
  }

  if (admin !== null) {
    return (
      <main className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold">{t('admin.title')}</h1>
        <p className="text-sm text-[var(--color-parent-muted)]">
          {t('admin.signedInAs', { email: admin.email })}
        </p>
        <section className="rounded-2xl border border-[var(--color-parent-line)] p-6">
          <h2 className="font-semibold">{t('admin.emptyTitle')}</h2>
          <p className="mt-1 text-sm text-[var(--color-parent-muted)]">{t('admin.emptyText')}</p>
        </section>
        <Button variant="secondary" onClick={() => setAdmin(null)}>
          {t('common.logout')}
        </Button>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-sm flex-col gap-5">
      <h1 className="text-2xl font-semibold">{t('admin.title')}</h1>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label={t('common.email')}>
          {({ id }) => (
            <Input
              id={id}
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          )}
        </Field>
        <Field label={t('common.password')}>
          {({ id }) => (
            <Input
              id={id}
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        <Field label={t('admin.totp')}>
          {({ id }) => (
            <Input
              id={id}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              required
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
            />
          )}
        </Field>
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button type="submit" block disabled={busy}>
          {busy ? t('common.working') : t('admin.submit')}
        </Button>
      </form>
    </main>
  );
}
