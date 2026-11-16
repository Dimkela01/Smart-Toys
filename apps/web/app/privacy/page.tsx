'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { PrivacySummary } from '@/components/PrivacySummary';
import { Card, Notice, Page } from '@/components/ui';
import { useT } from '@/lib/i18n';

export default function PrivacyPage(): ReactNode {
  const t = useT();
  return (
    <Page title={t('privacy.title')}>
      <Card>
        <PrivacySummary />
      </Card>
      <Notice>
        <strong>{t('privacy.demoTitle')}</strong> {t('privacy.demoText')}
      </Notice>
      <Link href="/" className="text-sm underline">
        {t('privacy.backHome')}
      </Link>
    </Page>
  );
}
