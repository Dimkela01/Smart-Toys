'use client';

/**
 * Four-digit PIN pad for leaving child mode (UC-21).
 *
 * There is deliberately no "forgot PIN" link here: a PIN is only reset from the parent
 * login (UC-21 AC).
 */

import { useState, type ReactNode } from 'react';

const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];

export function PinPad({
  title,
  cancelLabel,
  error,
  busy = false,
  onSubmit,
  onCancel,
}: {
  title: string;
  cancelLabel: string;
  error?: string;
  busy?: boolean;
  onSubmit: (pin: string) => void;
  onCancel: () => void;
}): ReactNode {
  const [pin, setPin] = useState('');

  const press = (digit: string) => {
    if (busy) return;
    const next = `${pin}${digit}`.slice(0, 4);
    setPin(next);
    if (next.length === 4) {
      onSubmit(next);
      setPin('');
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/55 p-5">
      <div className="w-full max-w-xs rounded-2xl bg-white p-5">
        <h2 className="text-center text-lg font-semibold">{title}</h2>

        <div className="my-4 flex justify-center gap-3" aria-hidden="true">
          {[0, 1, 2, 3].map((index) => (
            <span
              key={index}
              className={`h-4 w-4 rounded-full border-2 ${
                index < pin.length
                  ? 'border-[var(--color-parent-accent)] bg-[var(--color-parent-accent)]'
                  : 'border-[var(--color-parent-line)]'
              }`}
            />
          ))}
        </div>

        {error ? (
          <p role="alert" className="mb-3 text-center text-sm text-[var(--color-danger)]">
            {error}
          </p>
        ) : null}

        <div className="grid grid-cols-3 gap-2">
          {DIGITS.map((digit) => (
            <button
              key={digit}
              type="button"
              disabled={busy}
              onClick={() => press(digit)}
              className="min-h-16 rounded-xl border border-[var(--color-parent-line)] text-xl font-medium disabled:opacity-50"
            >
              {digit}
            </button>
          ))}
          <button
            type="button"
            onClick={onCancel}
            className="min-h-16 rounded-xl border border-transparent text-sm underline"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => press('0')}
            className="min-h-16 rounded-xl border border-[var(--color-parent-line)] text-xl font-medium disabled:opacity-50"
          >
            0
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setPin((current) => current.slice(0, -1))}
            aria-label="⌫"
            className="min-h-16 rounded-xl border border-[var(--color-parent-line)] text-xl disabled:opacity-50"
          >
            ⌫
          </button>
        </div>
      </div>
    </div>
  );
}
