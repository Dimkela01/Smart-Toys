'use client';

/** Registration with the 18+ and consent checkboxes, neither pre-ticked (F-02, UC-01). */

import Link from 'next/link';
import { useState, type ReactNode } from 'react';
import { PrivacySummary } from '@/components/PrivacySummary';
import { Button, Card, Field, Input, Notice, Page } from '@/components/ui';
import { ApiError, request } from '@/lib/api';
import { useT } from '@/lib/i18n';

export default function RegisterPage(): ReactNode {
  const t = useT();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [adult, setAdult] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    if (!adult || !consent) {
      setError(t('register.needBoth'));
      return;
    }
    setBusy(true);
    try {
      await request('/auth/register', {
        method: 'POST',
        body: {
          email,
          password,
          adult_confirmed: adult,
          consent_accepted: consent,
          locale: 'sr',
        },
      });
      setSent(true);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'rate_limited') {
        setError(t('common.rateLimited'));
      } else if (caught instanceof ApiError && caught.status === 422) {
        setError(t('register.passwordHint'));
      } else {
        setError(t('common.errorGeneric'));
      }
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <Page title={t('register.sentTitle')}>
        <p>{t('register.sentText')}</p>
        <Notice>{t('register.devHint')}</Notice>
        <Link href="/login" className="text-sm underline">
          {t('login.title')}
        </Link>
      </Page>
    );
  }

  return (
    <Page title={t('register.title')}>
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

        <Field label={t('common.password')} hint={t('register.passwordHint')}>
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="password"
              name="password"
              autoComplete="new-password"
              minLength={10}
              required
              aria-describedby={describedBy}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>

        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            name="adult_confirmed"
            className="mt-1 h-5 w-5"
            checked={adult}
            onChange={(event) => setAdult(event.target.checked)}
          />
          <span>{t('register.adultLabel')}</span>
        </label>

        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            name="consent_accepted"
            className="mt-1 h-5 w-5"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
          />
          <span>{t('register.consentLabel')}</span>
        </label>

        <details>
          <summary className="cursor-pointer text-sm underline">
            {t('register.consentExpand')}
          </summary>
          <Card className="mt-2">
            <PrivacySummary />
          </Card>
        </details>

        {error ? <Notice tone="error">{error}</Notice> : null}

        <Button type="submit" block disabled={busy}>
          {busy ? t('common.working') : t('register.submit')}
        </Button>
      </form>

      <p className="text-sm">
        {t('register.haveAccount')}{' '}
        <Link href="/login" className="underline">
          {t('login.submit')}
        </Link>
      </p>
    </Page>
  );
}
