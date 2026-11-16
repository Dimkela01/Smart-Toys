'use client';

/**
 * Tiny dictionary-based i18n (docs/CLAUDE.md §3: no hard-coded user-facing text).
 *
 * There is no locale in the URL on purpose: the parent UI follows the parent's account
 * language and the child UI follows that child's language, so one device can show a
 * Serbian toy screen to a Serbian-speaking child and an English parent dashboard.
 */

import { createContext, useContext, useMemo, type ReactNode } from 'react';
import en from '@/messages/en.json';
import sr from '@/messages/sr.json';

export type Locale = 'sr' | 'en';
export const LOCALES: Locale[] = ['sr', 'en'];
export const DEFAULT_LOCALE: Locale = 'sr';

const dictionaries: Record<Locale, unknown> = { sr, en };

export function isLocale(value: unknown): value is Locale {
  return value === 'sr' || value === 'en';
}

function lookup(dictionary: unknown, key: string): string | undefined {
  let node: unknown = dictionary;
  for (const part of key.split('.')) {
    if (typeof node !== 'object' || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === 'string' ? node : undefined;
}

export type Vars = Record<string, string | number>;

export function translate(locale: Locale, key: string, vars?: Vars): string {
  const found = lookup(dictionaries[locale], key) ?? lookup(dictionaries[DEFAULT_LOCALE], key);
  if (found === undefined) {
    if (process.env.NODE_ENV !== 'production') {
      // a missing key is a bug, not something a parent should ever read
      console.warn(`[i18n] missing key: ${key}`);
    }
    return key;
  }
  if (!vars) return found;
  return found.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

const LocaleContext = createContext<Locale>(DEFAULT_LOCALE);

export function LocaleProvider({
  locale,
  children,
}: {
  locale: Locale;
  children: ReactNode;
}): ReactNode {
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

export function useLocale(): Locale {
  return useContext(LocaleContext);
}

export type Translator = (key: string, vars?: Vars) => string;

export function useT(): Translator {
  const locale = useLocale();
  return useMemo(() => (key: string, vars?: Vars) => translate(locale, key, vars), [locale]);
}
