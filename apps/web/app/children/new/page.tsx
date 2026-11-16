'use client';

/**
 * Add-child wizard, three steps (UC-03, UI.md §2).
 *
 * Step 3 shows the UC-04 defaults read-only before confirming; the screen that changes
 * them is M5. The character voice sample needs TTS and arrives in M2.
 */

import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { Avatar } from '@/components/Avatar';
import { Button, Card, Field, Input, Notice, Page, Spinner } from '@/components/ui';
import { ApiError, catalog, type Catalog, type Child } from '@/lib/api';
import { useT } from '@/lib/i18n';
import { useSession } from '@/lib/session';

const TOTAL_STEPS = 3;

export default function AddChildPage(): ReactNode {
  const t = useT();
  const router = useRouter();
  const { status, call } = useSession();

  const [data, setData] = useState<Catalog | null>(null);
  const [taken, setTaken] = useState<Set<string>>(new Set());
  const [step, setStep] = useState(1);

  const [nickname, setNickname] = useState('');
  const [age, setAge] = useState(6);
  const [language, setLanguage] = useState<'sr' | 'en'>('sr');
  const [interests, setInterests] = useState<string[]>([]);
  const [custom, setCustom] = useState('');
  const [avatarId, setAvatarId] = useState<string | null>(null);
  const [characterId, setCharacterId] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === 'anonymous') router.replace('/login');
    if (status === 'child_mode') router.replace('/child');
  }, [status, router]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [loaded, existing] = await Promise.all([
          catalog(),
          call<Child[]>('/children').catch(() => [] as Child[]),
        ]);
        if (cancelled) return;
        setData(loaded);
        setTaken(new Set(existing.map((child) => child.avatar_id)));
        setCharacterId(loaded.characters[0]?.id ?? null);
      } catch {
        if (!cancelled) setError(t('common.errorGeneric'));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [call, t]);

  function toggleInterest(value: string): void {
    setInterests((current) => {
      if (current.includes(value)) return current.filter((item) => item !== value);
      if (data && current.length >= data.limits.max_interests) return current;
      return [...current, value];
    });
  }

  async function create(): Promise<void> {
    if (!avatarId) return;
    setError(null);
    setBusy(true);
    try {
      await call<Child>('/children', {
        method: 'POST',
        body: {
          nickname,
          age,
          language,
          interests,
          avatar_id: avatarId,
          character_id: characterId,
        },
      });
      router.replace('/dashboard');
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'avatar_taken') {
        setError(t('wizard.avatarTaken'));
        setStep(2);
      } else if (caught instanceof ApiError && caught.code === 'child_limit_reached') {
        setError(t('wizard.childLimit'));
      } else if (caught instanceof ApiError && caught.status === 422) {
        setError(t('wizard.nicknameHint'));
        setStep(1);
      } else {
        setError(t('common.errorGeneric'));
      }
    } finally {
      setBusy(false);
    }
  }

  if (status !== 'signed_in' || data === null) {
    return (
      <Page>
        <Spinner label={t('common.loading')} />
      </Page>
    );
  }

  const ages = Array.from(
    { length: data.limits.age_max - data.limits.age_min + 1 },
    (_, index) => data.limits.age_min + index,
  );

  return (
    <Page title={t(`wizard.step${step}Title`)}>
      <p className="text-sm text-[var(--color-parent-muted)]">
        {t('wizard.stepOf', { current: step, total: TOTAL_STEPS })}
      </p>

      {error ? <Notice tone="error">{error}</Notice> : null}

      {step === 1 ? (
        <div className="flex flex-col gap-4">
          <Field label={t('wizard.nicknameLabel')} hint={t('wizard.nicknameHint')}>
            {({ id, describedBy }) => (
              <Input
                id={id}
                value={nickname}
                maxLength={data.limits.nickname_max_length}
                required
                aria-describedby={describedBy}
                onChange={(event) => setNickname(event.target.value)}
              />
            )}
          </Field>

          <Field label={t('wizard.ageLabel')}>
            {({ id }) => (
              <div id={id} className="flex flex-wrap gap-2">
                {ages.map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={age === value}
                    onClick={() => setAge(value)}
                    className={`min-h-12 min-w-12 rounded-xl border px-3 ${
                      age === value
                        ? 'border-[var(--color-parent-accent)] bg-[var(--color-parent-accent)] text-white'
                        : 'border-[var(--color-parent-line)] bg-white'
                    }`}
                  >
                    {value}
                  </button>
                ))}
              </div>
            )}
          </Field>

          <Field label={t('wizard.languageLabel')}>
            {({ id }) => (
              <div id={id} className="flex gap-2">
                {data.languages.map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={language === value}
                    onClick={() => setLanguage(value)}
                    className={`min-h-12 flex-1 rounded-xl border px-3 ${
                      language === value
                        ? 'border-[var(--color-parent-accent)] bg-[var(--color-parent-accent)] text-white'
                        : 'border-[var(--color-parent-line)] bg-white'
                    }`}
                  >
                    {value === 'sr' ? t('wizard.langSr') : t('wizard.langEn')}
                  </button>
                ))}
              </div>
            )}
          </Field>

          <Button block disabled={nickname.trim().length === 0} onClick={() => setStep(2)}>
            {t('common.next')}
          </Button>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="flex flex-col gap-4">
          <Field label={t('wizard.interestsLabel')}>
            {({ id }) => (
              <div id={id} className="flex flex-wrap gap-2">
                {data.interest_suggestions.map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={interests.includes(value)}
                    onClick={() => toggleInterest(value)}
                    className={`min-h-12 rounded-full border px-4 text-sm ${
                      interests.includes(value)
                        ? 'border-[var(--color-parent-accent)] bg-[var(--color-parent-accent)] text-white'
                        : 'border-[var(--color-parent-line)] bg-white'
                    }`}
                  >
                    {t(`interests.${value}`)}
                  </button>
                ))}
                {interests
                  .filter((value) => !data.interest_suggestions.includes(value))
                  .map((value) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed
                      onClick={() => toggleInterest(value)}
                      className="min-h-12 rounded-full border border-[var(--color-parent-accent)] bg-[var(--color-parent-accent)] px-4 text-sm text-white"
                    >
                      {value}
                    </button>
                  ))}
              </div>
            )}
          </Field>

          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Field label={t('wizard.customInterest')}>
                {({ id }) => (
                  <Input
                    id={id}
                    value={custom}
                    maxLength={30}
                    onChange={(event) => setCustom(event.target.value)}
                  />
                )}
              </Field>
            </div>
            <Button
              variant="secondary"
              disabled={custom.trim().length === 0 || interests.length >= data.limits.max_interests}
              onClick={() => {
                toggleInterest(custom.trim());
                setCustom('');
              }}
            >
              {t('wizard.add')}
            </Button>
          </div>

          <Field label={t('wizard.avatarLabel')} hint={t('wizard.avatarHint')}>
            {({ id, describedBy }) => (
              <div id={id} aria-describedby={describedBy} className="grid grid-cols-4 gap-2">
                {data.avatars.map((avatar) => {
                  const isTaken = taken.has(avatar.id);
                  return (
                    <button
                      key={avatar.id}
                      type="button"
                      disabled={isTaken}
                      aria-pressed={avatarId === avatar.id}
                      aria-label={avatar.label[language] ?? avatar.id}
                      onClick={() => setAvatarId(avatar.id)}
                      className={`rounded-2xl border-4 p-0.5 disabled:opacity-30 ${
                        avatarId === avatar.id
                          ? 'border-[var(--color-parent-accent)]'
                          : 'border-transparent'
                      }`}
                    >
                      <Avatar
                        avatarId={avatar.id}
                        label={avatar.label[language] ?? avatar.id}
                        size={64}
                      />
                    </button>
                  );
                })}
              </div>
            )}
          </Field>

          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setStep(1)}>
              {t('common.back')}
            </Button>
            <Button block disabled={avatarId === null} onClick={() => setStep(3)}>
              {t('common.next')}
            </Button>
          </div>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="flex flex-col gap-4">
          <Field label={t('wizard.characterLabel')}>
            {({ id }) => (
              <div id={id} className="flex flex-col gap-2">
                {data.characters.map((character) => (
                  <button
                    key={character.id}
                    type="button"
                    aria-pressed={characterId === character.id}
                    onClick={() => setCharacterId(character.id)}
                    className={`flex min-h-16 items-center gap-3 rounded-xl border px-3 py-2 text-left ${
                      characterId === character.id
                        ? 'border-[var(--color-parent-accent)]'
                        : 'border-[var(--color-parent-line)]'
                    }`}
                  >
                    <span className="text-base font-medium">
                      {character.name[language] ?? character.id}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Field>

          <Notice>{t('wizard.sampleUnavailable')}</Notice>

          <Card>
            <h2 className="font-semibold">{t('wizard.defaultsTitle')}</h2>
            <p className="mt-1 text-sm text-[var(--color-parent-muted)]">
              {t('wizard.defaultsText')}
            </p>
          </Card>

          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setStep(2)}>
              {t('common.back')}
            </Button>
            <Button block disabled={busy} onClick={create}>
              {busy ? t('common.working') : t('wizard.create')}
            </Button>
          </div>
        </div>
      ) : null}
    </Page>
  );
}
