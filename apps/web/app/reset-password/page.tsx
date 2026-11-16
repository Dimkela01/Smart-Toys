'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Suspense, useState, type ReactNode } from 'react';
import { Button, Field, Input, Notice, Page } from '@/components/ui';
import { ApiError, request } from '@/lib/api';
import { useT } from '@/lib/i18n';

function ResetPassword(): ReactNode {
  const t = useT();
  const token = useSearchParams().get('token');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!token) {
    return (
      <Page title={t('reset.invalidTitle')}>
        <p>{t('reset.invalidText')}</p>
        <Link href="/forgot-password" className="text-sm underline">
          {t('forgot.submit')}
        </Link>
      </Page>
    );
  }

  if (done) {
    return (
      <Page title={t('reset.doneTitle')}>
        <p>{t('reset.doneText')}</p>
        <Link href="/login">
          <Button block>{t('login.submit')}</Button>
        </Link>
      </Page>
    );
  }

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await request('/auth/password-reset/confirm', {
        method: 'POST',
        body: { token, password },
      });
      setDone(true);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 400) {
        setError(t('reset.invalidText'));
      } else if (caught instanceof ApiError && caught.status === 422) {
        setError(t('register.passwordHint'));
      } else {
        setError(t('common.errorGeneric'));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page title={t('reset.title')}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label={t('reset.newPassword')} hint={t('register.passwordHint')}>
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="password"
              autoComplete="new-password"
              minLength={10}
              required
              aria-describedby={describedBy}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button type="submit" block disabled={busy}>
          {busy ? t('common.working') : t('reset.submit')}
        </Button>
      </form>
    </Page>
  );
}

export default function ResetPasswordPage(): ReactNode {
  return (
    <Suspense fallback={null}>
      <ResetPassword />
    </Suspense>
  );
}
