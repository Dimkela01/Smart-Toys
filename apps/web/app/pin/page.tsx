'use client';

/** Set the parent PIN, entered twice (UC-01 step 5). */

import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { Button, Field, Input, Notice, Page, Spinner } from '@/components/ui';
import { ApiError, type MeResponse } from '@/lib/api';
import { useT } from '@/lib/i18n';
import { useSession } from '@/lib/session';

export default function PinPage(): ReactNode {
  const t = useT();
  const router = useRouter();
  const { status, requires, call, applyMe } = useSession();
  const [pin, setPin] = useState('');
  const [repeat, setRepeat] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === 'anonymous') router.replace('/login');
    if (status === 'child_mode') router.replace('/child');
  }, [status, router]);

  if (status === 'loading') {
    return (
      <Page>
        <Spinner label={t('common.loading')} />
      </Page>
    );
  }

  const needsVerification = requires.includes('email_verification');

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    if (pin !== repeat) {
      setError(t('pin.mismatch'));
      return;
    }
    setBusy(true);
    try {
      // the response carries the new account state, so the gate clears immediately
      applyMe(
        await call<MeResponse>('/auth/pin', {
          method: 'POST',
          body: { pin, pin_repeat: repeat },
        }),
      );
      router.replace('/dashboard');
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'pin_locked') {
        setError(t('pin.locked'));
      } else if (caught instanceof ApiError && caught.code === 'email_not_verified') {
        setError(t('dashboard.needVerify'));
      } else if (caught instanceof ApiError && caught.status === 422) {
        setError(t('pin.lead'));
      } else {
        setError(t('common.errorGeneric'));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page title={t('pin.title')}>
      <p className="text-sm text-[var(--color-parent-muted)]">{t('pin.lead')}</p>
      {needsVerification ? <Notice tone="error">{t('dashboard.needVerify')}</Notice> : null}

      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label={t('pin.pinLabel')}>
          {({ id }) => (
            <Input
              id={id}
              type="password"
              inputMode="numeric"
              autoComplete="new-password"
              pattern="[0-9]{4}"
              maxLength={4}
              required
              value={pin}
              onChange={(event) => setPin(event.target.value.replace(/\D/g, ''))}
            />
          )}
        </Field>

        <Field label={t('pin.repeatLabel')}>
          {({ id }) => (
            <Input
              id={id}
              type="password"
              inputMode="numeric"
              autoComplete="new-password"
              pattern="[0-9]{4}"
              maxLength={4}
              required
              value={repeat}
              onChange={(event) => setRepeat(event.target.value.replace(/\D/g, ''))}
            />
          )}
        </Field>

        {error ? <Notice tone="error">{error}</Notice> : null}

        <Button type="submit" block disabled={busy || needsVerification}>
          {busy ? t('common.working') : t('pin.submit')}
        </Button>
      </form>
    </Page>
  );
}
