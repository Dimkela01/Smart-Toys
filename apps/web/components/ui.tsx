'use client';

/**
 * Parent-side building blocks: calm, standard mobile app (UI.md), WCAG 2.1 AA contrast,
 * labelled inputs, works at 200% text size (NFR-08).
 */

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';
import { useId } from 'react';

export function Page({
  title,
  children,
  footer,
}: {
  title?: string;
  children: ReactNode;
  footer?: ReactNode;
}): ReactNode {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col gap-6 px-5 py-8">
      {title ? <h1 className="text-2xl leading-tight font-semibold">{title}</h1> : null}
      {children}
      {footer ? <div className="mt-auto pt-4 text-sm">{footer}</div> : null}
    </main>
  );
}

export function Card({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}): ReactNode {
  return (
    <section
      className={`rounded-2xl border border-[var(--color-parent-line)] bg-white p-4 ${className}`}
    >
      {children}
    </section>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger';
  block?: boolean;
};

export function Button({
  variant = 'primary',
  block = false,
  className = '',
  ...props
}: ButtonProps): ReactNode {
  const styles: Record<string, string> = {
    primary:
      'bg-[var(--color-parent-accent)] text-[var(--color-parent-accent-ink)] border-transparent',
    secondary: 'bg-white text-[var(--color-parent-ink)] border-[var(--color-parent-line)]',
    quiet: 'bg-transparent text-[var(--color-parent-accent)] border-transparent underline',
    danger: 'bg-white text-[var(--color-danger)] border-[var(--color-danger)]',
  };
  return (
    <button
      // touch targets stay comfortable on a phone (NFR-07 applies to the child UI; the
      // parent UI simply keeps the same minimum)
      className={`min-h-12 rounded-xl border px-4 py-3 text-base font-medium disabled:opacity-50 ${
        styles[variant] ?? ''
      } ${block ? 'w-full' : ''} ${className}`}
      {...props}
    />
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (props: { id: string; describedBy: string | undefined }) => ReactNode;
}): ReactNode {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children({ id, describedBy })}
      {hint ? (
        <p id={hintId} className="text-sm text-[var(--color-parent-muted)]">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-sm text-[var(--color-danger)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>): ReactNode {
  return (
    <input
      className="min-h-12 rounded-xl border border-[var(--color-parent-line)] bg-white px-3 py-2 text-base"
      {...props}
    />
  );
}

export function Notice({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'error';
  children: ReactNode;
}): ReactNode {
  const styles =
    tone === 'error'
      ? 'border-[var(--color-danger)] text-[var(--color-danger)]'
      : 'border-[var(--color-parent-line)] text-[var(--color-parent-muted)]';
  return (
    <p
      role={tone === 'error' ? 'alert' : undefined}
      className={`rounded-xl border bg-white px-3 py-2 text-sm ${styles}`}
    >
      {children}
    </p>
  );
}

export function Spinner({ label }: { label: string }): ReactNode {
  return (
    <p role="status" className="text-sm text-[var(--color-parent-muted)]">
      {label}
    </p>
  );
}
