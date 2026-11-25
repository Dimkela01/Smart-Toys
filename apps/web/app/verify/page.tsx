'use client';

/** Target of the verification link; signs the parent in and continues to the PIN (UC-01). */

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState, type ReactNode } from 'react';
import { Button, Field, Input, Notice, Page, Spinner } from '@/components/ui';
import { request, type SessionResponse } from '@/lib/api';
import { deviceId } from '@/lib/device';
import { useT } from '@/lib/i18n';
import { useSession } from '@/lib/session';

type State = 'working' | 'done' | 'failed';

function Verify(): ReactNode {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const { adopt } = useSession();
  const [state, setState] = useState<State>('working');
  const [resent, setResent] = useState(false);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const token = params.get('token');

  useEffect(() => {
    if (!token) {
      setState('failed');
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const session = await request<SessionResponse>('/auth/verify', {
          method: 'POST',
          // without this every browser that opens a link looks like the same device
          body: { token, device_id: deviceId() },
        });
        if (cancelled) return;
        adopt(session);
        setState('done');
      } catch {
        if (!cancelled) setState('failed');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, adopt]);

  if (state === 'working') {
    return (
      <Page>
        <Spinner label={t('verify.working')} />
      </Page>
    );
  }

  if (state === 'done') {
    return (
      <Page title={t('verify.successTitle')}>
        <p>{t('verify.successText')}</p>
        <Button block onClick={() => router.replace('/pin')}>
          {t('verify.toPin')}
        </Button>
      </Page>
    );
  }

  return (
    <Page title={t('verify.failedTitle')}>
      <p>{token ? t('verify.failedText') : t('verify.missingToken')}</p>

      <form
        className="flex flex-col gap-3"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          try {
            // the answer is the same whether or not the address exists (UC-01)
            await request('/auth/verify/resend', { method: 'POST', body: { email } });
          } finally {
            setBusy(false);
            setResent(true);
          }
        }}
      >
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
        <Button type="submit" variant="secondary" block disabled={busy}>
          {busy ? t('common.working') : t('verify.resend')}
        </Button>
      </form>

      {resent ? <Notice>{t('verify.resent')}</Notice> : null}
      <Notice>{t('register.devHint')}</Notice>
      <Link href="/login" className="text-sm underline">
        {t('login.title')}
      </Link>
    </Page>
  );
}

export default function VerifyPage(): ReactNode {
  return (
    <Suspense fallback={null}>
      <Verify />
    </Suspense>
  );
}
