'use client';

import Link from 'next/link';
import { useState, type ReactNode } from 'react';
import { Button, Field, Input, Notice, Page } from '@/components/ui';
import { request } from '@/lib/api';
import { useT } from '@/lib/i18n';

export default function ForgotPasswordPage(): ReactNode {
  const t = useT();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    try {
      await request('/auth/password-reset/request', { method: 'POST', body: { email } });
    } finally {
      // the same answer either way, so the form cannot be used to find accounts (UC-02)
      setBusy(false);
      setSent(true);
    }
  }

  if (sent) {
    return (
      <Page title={t('forgot.sentTitle')}>
        <p>{t('forgot.sentText')}</p>
        <Notice>{t('register.devHint')}</Notice>
        <Link href="/login" className="text-sm underline">
          {t('forgot.toLogin')}
        </Link>
      </Page>
    );
  }

  return (
    <Page title={t('forgot.title')}>
      <p className="text-sm text-[var(--color-parent-muted)]">{t('forgot.lead')}</p>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label={t('common.email')}>
          {({ id }) => (
            <Input
              id={id}
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          )}
        </Field>
        <Button type="submit" block disabled={busy}>
          {busy ? t('common.working') : t('forgot.submit')}
        </Button>
      </form>
      <Link href="/login" className="text-sm underline">
        {t('forgot.toLogin')}
      </Link>
    </Page>
  );
}
