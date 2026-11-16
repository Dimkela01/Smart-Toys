'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { Button, Notice, Page, Spinner } from '@/components/ui';
import { useT } from '@/lib/i18n';
import { useSession } from '@/lib/session';

export default function Landing(): ReactNode {
  const t = useT();
  const router = useRouter();
  const { status } = useSession();

  useEffect(() => {
    if (status === 'signed_in') router.replace('/dashboard');
    // a locked device belongs to the child, not to whoever opens the page
    if (status === 'child_mode') router.replace('/child');
  }, [status, router]);

  if (status === 'loading') {
    return (
      <Page>
        <Spinner label={t('common.loading')} />
      </Page>
    );
  }

  return (
    <Page>
      <header className="flex flex-col gap-3">
        <p className="text-sm font-medium tracking-wide text-[var(--color-parent-accent)]">
          {t('common.appName')}
        </p>
        <h1 className="text-3xl leading-tight font-semibold">{t('landing.title')}</h1>
        <p className="text-base text-[var(--color-parent-muted)]">{t('landing.lead')}</p>
      </header>

      <ul className="flex flex-col gap-2 text-sm">
        <li>{t('landing.point1')}</li>
        <li>{t('landing.point2')}</li>
        <li>{t('landing.point3')}</li>
      </ul>

      <Notice>{t('landing.demoNotice')}</Notice>

      <div className="flex flex-col gap-3">
        <Link href="/register">
          <Button block>{t('landing.createAccount')}</Button>
        </Link>
        <Link href="/login">
          <Button block variant="secondary">
            {t('landing.logIn')}
          </Button>
        </Link>
      </div>

      <Link href="/privacy" className="text-sm underline">
        {t('landing.privacyLink')}
      </Link>
    </Page>
  );
}
