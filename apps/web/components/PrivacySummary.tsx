'use client';

/**
 * The privacy summary a parent must read before consenting (F-02, UC-01 step 3).
 * Shown on its own page and expandable inside the registration form.
 */

import type { ReactNode } from 'react';
import { useT } from '@/lib/i18n';

export function PrivacySummary(): ReactNode {
  const t = useT();
  return (
    <div className="flex flex-col gap-4 text-sm">
      <section>
        <h2 className="font-semibold">{t('privacy.storedTitle')}</h2>
        <ul className="mt-1 flex flex-col gap-1">
          <li>{t('privacy.stored1')}</li>
          <li>{t('privacy.stored2')}</li>
          <li>{t('privacy.stored3')}</li>
        </ul>
      </section>
      <section>
        <h2 className="font-semibold">{t('privacy.notStoredTitle')}</h2>
        <ul className="mt-1 flex flex-col gap-1">
          <li>{t('privacy.notStored1')}</li>
          <li>{t('privacy.notStored2')}</li>
        </ul>
      </section>
      <section>
        <h2 className="font-semibold">{t('privacy.retentionTitle')}</h2>
        <p className="mt-1">{t('privacy.retentionText')}</p>
      </section>
      <section>
        <h2 className="font-semibold">{t('privacy.whoTitle')}</h2>
        <p className="mt-1">{t('privacy.whoText')}</p>
      </section>
    </div>
  );
}
