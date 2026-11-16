'use client';

/**
 * Parent dashboard, M1 scope: one card per child and the "Give to child" button (UC-05).
 * Usage rings, summaries, topic tags and alerts arrive in M5 (F-13).
 */

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Avatar } from '@/components/Avatar';
import { Button, Card, Notice, Page, Spinner } from '@/components/ui';
import { ApiError, type Child, type EnterChildModeResponse } from '@/lib/api';
import { setChildMode } from '@/lib/childSession';
import { useT } from '@/lib/i18n';
import { useSession } from '@/lib/session';

export default function DashboardPage(): ReactNode {
  const t = useT();
  const router = useRouter();
  const { status, requires, parent, call, logout } = useSession();
  const [children, setChildren] = useState<Child[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (status === 'anonymous') router.replace('/login');
    if (status === 'child_mode') router.replace('/child');
  }, [status, router]);

  const load = useCallback(async () => {
    try {
      setChildren(await call<Child[]>('/children'));
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'email_not_verified') {
        router.replace('/verify');
      } else if (caught instanceof ApiError && caught.code === 'pin_not_set') {
        router.replace('/pin');
      } else {
        setError(t('common.errorGeneric'));
      }
    }
  }, [call, router, t]);

  useEffect(() => {
    if (status === 'signed_in' && requires.length === 0) void load();
  }, [status, requires.length, load]);

  async function giveToChild(): Promise<void> {
    setError(null);
    setBusy(true);
    try {
      const entered = await call<EnterChildModeResponse>('/child-mode/enter', {
        method: 'POST',
      });
      setChildMode(entered.token, entered.children);
      router.replace('/child');
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'no_device_session') {
        setError(t('dashboard.noDeviceSession'));
      } else if (caught instanceof ApiError && caught.code === 'no_children') {
        setError(t('dashboard.noChildrenText'));
      } else {
        setError(t('common.errorGeneric'));
      }
    } finally {
      setBusy(false);
    }
  }

  if (status !== 'signed_in') {
    return (
      <Page>
        <Spinner label={t('common.loading')} />
      </Page>
    );
  }

  if (requires.includes('email_verification')) {
    return (
      <Page title={t('dashboard.title')}>
        <Notice tone="error">{t('dashboard.needVerify')}</Notice>
      </Page>
    );
  }

  if (requires.includes('pin')) {
    return (
      <Page title={t('dashboard.title')}>
        <Notice tone="error">{t('dashboard.needPin')}</Notice>
        <Link href="/pin">
          <Button block>{t('pin.submit')}</Button>
        </Link>
      </Page>
    );
  }

  return (
    <Page
      title={t('dashboard.title')}
      footer={
        <div className="flex items-center justify-between gap-3">
          <span className="truncate text-[var(--color-parent-muted)]">{parent?.email}</span>
          <Button
            variant="quiet"
            // no redirect here: the guard above owns where an anonymous visitor goes,
            // otherwise the two race and the landing page wins only sometimes
            className="shrink-0 whitespace-nowrap"
            onClick={() => void logout()}
          >
            {t('common.logout')}
          </Button>
        </div>
      }
    >
      {error ? <Notice tone="error">{error}</Notice> : null}

      {children === null ? <Spinner label={t('common.loading')} /> : null}

      {children !== null && children.length === 0 ? (
        <Card>
          <h2 className="font-semibold">{t('dashboard.noChildrenTitle')}</h2>
          <p className="mt-1 text-sm text-[var(--color-parent-muted)]">
            {t('dashboard.noChildrenText')}
          </p>
        </Card>
      ) : null}

      {children?.map((child) => (
        <Card key={child.id}>
          <div className="flex items-center gap-3">
            <Avatar avatarId={child.avatar_id} label={child.nickname} size={64} />
            <div>
              <h2 className="text-lg font-semibold">{child.nickname}</h2>
              <p className="text-sm text-[var(--color-parent-muted)]">
                {t('dashboard.ageYears', { age: child.age })}
              </p>
            </div>
          </div>
          <dl className="mt-3 flex flex-col gap-1 text-sm text-[var(--color-parent-muted)]">
            <div>{t('dashboard.limitMinutes', { minutes: child.settings.daily_limit_min })}</div>
            <div>
              {t('dashboard.hours', {
                from: child.settings.allowed_from.slice(0, 5),
                to: child.settings.allowed_to.slice(0, 5),
              })}
            </div>
            <div>
              {child.settings.memory_enabled ? t('dashboard.memoryOn') : t('dashboard.memoryOff')}
            </div>
            <div>
              {child.settings.transcripts_visible
                ? t('dashboard.transcriptsOn')
                : t('dashboard.transcriptsOff')}
            </div>
          </dl>
          <p className="mt-3 text-sm text-[var(--color-parent-muted)]">
            {t('dashboard.summariesSoon')}
          </p>
        </Card>
      ))}

      <div className="flex flex-col gap-3">
        <Button block disabled={busy || !children || children.length === 0} onClick={giveToChild}>
          {busy ? t('common.working') : t('dashboard.giveToChild')}
        </Button>
        <Link href="/children/new">
          <Button block variant="secondary">
            {t('dashboard.addChild')}
          </Button>
        </Link>
      </div>
    </Page>
  );
}
