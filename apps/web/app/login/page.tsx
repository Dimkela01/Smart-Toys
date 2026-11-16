'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, type ReactNode } from 'react';
import { Button, Field, Input, Notice, Page } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { useT } from '@/lib/i18n';
import { useSession } from '@/lib/session';

export default function LoginPage(): ReactNode {
  const t = useT();
  const router = useRouter();
  const { login } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const session = await login(email, password);
      // the gate decides where the parent lands next (UC-01 AC)
      if (session.requires.includes('email_verification')) router.replace('/verify');
      else if (session.requires.includes('pin')) router.replace('/pin');
      else router.replace('/dashboard');
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'account_locked') {
        setError(t('login.accountLocked'));
      } else if (caught instanceof ApiError && caught.code === 'rate_limited') {
        setError(t('common.rateLimited'));
      } else if (caught instanceof ApiError && caught.status === 401) {
        setError(t('login.invalidCredentials'));
      } else {
        setError(t('common.errorGeneric'));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page title={t('login.title')}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label={t('common.email')}>
          {({ id }) => (
            <Input
              id={id}
              type="email"
              name="email"
              autoComplete="email"
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
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>

        {error ? <Notice tone="error">{error}</Notice> : null}

        <Button type="submit" block disabled={busy}>
          {busy ? t('common.working') : t('login.submit')}
        </Button>
      </form>

      <div className="flex flex-col gap-2 text-sm">
        <Link href="/forgot-password" className="underline">
          {t('login.forgot')}
        </Link>
        <span>
          {t('login.noAccount')}{' '}
          <Link href="/register" className="underline">
            {t('register.submit')}
          </Link>
        </span>
      </div>
    </Page>
  );
}
