'use client';

/**
 * Placeholder character with the seven states from UI.md §3.3.
 *
 * The state names are the contract: M7 swaps this SVG for a Rive file driven by the same
 * state machine. While Bruno speaks, `mouth` is the RMS of the audio actually playing,
 * so the mouth follows the waveform rather than a timer - a child notices the difference
 * immediately. Nothing here shows text, because the child screen is voice only
 * (docs/CLAUDE.md §2).
 */

import type { ReactNode } from 'react';

export const CHARACTER_STATES = [
  'sleeping',
  'idle',
  'listening',
  'thinking',
  'speaking',
  'happy',
  'goodbye',
] as const;

export type CharacterState = (typeof CHARACTER_STATES)[number];

const palette: Record<string, { body: string; ear: string; accent: string }> = {
  bear: { body: '#A9713F', ear: '#8A5A31', accent: '#D8A974' },
  bunny: { body: '#C9C4DE', ear: '#B3ACCB', accent: '#EDE9F5' },
  robot: { body: '#6E8BA8', ear: '#54708B', accent: '#A8C0D6' },
};

export function Character({
  characterId,
  state,
  label,
  mouth = 0,
}: {
  characterId: string;
  state: CharacterState;
  /** For screen readers only; the child never reads it. */
  label: string;
  /** Output RMS, 0 to about 0.3. Only used while speaking. */
  mouth?: number;
}): ReactNode {
  const colors = palette[characterId] ?? palette.bear!;
  const eyesClosed = state === 'sleeping' || state === 'goodbye';
  // the curve's depth, in SVG units: a closed mouth at silence, wide open at a shout
  const open = state === 'speaking' ? 6 + Math.min(1, mouth * 7) * 30 : 0;
  const mouthPath =
    state === 'speaking'
      ? `M100 ${(156 - open / 4).toFixed(1)} q20 ${open.toFixed(1)} 40 0`
      : state === 'happy'
        ? 'M98 152 q22 26 44 0'
        : 'M104 158 q16 14 32 0';

  return (
    <div className={`character character--${state}`} aria-label={label} role="img">
      <svg viewBox="0 0 240 240" className="h-full w-full">
        <g className="character__ears">
          <circle cx="78" cy="58" r="26" fill={colors.ear} />
          <circle cx="162" cy="58" r="26" fill={colors.ear} />
        </g>
        <circle cx="120" cy="132" r="78" fill={colors.body} />
        <ellipse cx="120" cy="160" rx="42" ry="34" fill={colors.accent} />
        <g className="character__eyes" fill="#2b2b2b">
          {eyesClosed ? (
            <>
              <path d="M88 118 q10 8 20 0" stroke="#2b2b2b" strokeWidth="5" fill="none" />
              <path d="M132 118 q10 8 20 0" stroke="#2b2b2b" strokeWidth="5" fill="none" />
            </>
          ) : (
            <>
              <circle cx="98" cy={state === 'thinking' ? 112 : 118} r="8" />
              <circle cx="142" cy={state === 'thinking' ? 112 : 118} r="8" />
            </>
          )}
        </g>
        <path
          className="character__mouth"
          d={mouthPath}
          fill="none"
          stroke="#2b2b2b"
          strokeWidth="6"
          strokeLinecap="round"
        />
        {state === 'sleeping' ? (
          <text x="180" y="70" fontSize="26" fill="#2b2b2b" opacity="0.55">
            z
          </text>
        ) : null}
        {state === 'thinking' ? (
          <g className="character__dots" fill="#2b2b2b" opacity="0.6">
            <circle cx="176" cy="92" r="5" />
            <circle cx="192" cy="84" r="4" />
            <circle cx="206" cy="78" r="3" />
          </g>
        ) : null}
        {state === 'happy' ? (
          <g fill="#F6C85F">
            <path d="M44 70 l6 14 14 6 -14 6 -6 14 -6 -14 -14 -6 14 -6 Z" />
            <path d="M200 44 l5 11 11 5 -11 5 -5 11 -5 -11 -11 -5 11 -5 Z" />
          </g>
        ) : null}
      </svg>

      <style jsx>{`
        /*
         * Fills whatever space the toy screen gives it and no more. The SVG viewBox keeps
         * the proportions, so a short landscape window shrinks the character instead of
         * pushing the paw off the bottom.
         */
        .character {
          width: 100%;
          height: 100%;
          max-width: min(60vh, 90vw);
        }
        /* calm movement only, no flashing (UI.md §4) */
        .character--idle,
        .character--sleeping {
          animation: breathe 4.5s ease-in-out infinite;
        }
        .character--listening {
          animation: lean 1.8s ease-in-out infinite;
        }
        .character--thinking {
          animation: tilt 2.4s ease-in-out infinite;
        }
        .character--speaking {
          animation: talk 0.55s ease-in-out infinite;
        }
        .character--happy {
          animation: jump 0.7s ease-in-out infinite;
        }
        .character--goodbye {
          animation: wave 2.4s ease-in-out infinite;
        }
        @keyframes breathe {
          0%,
          100% {
            transform: scale(1);
          }
          50% {
            transform: scale(1.025);
          }
        }
        @keyframes lean {
          0%,
          100% {
            transform: translateY(0) scale(1.02);
          }
          50% {
            transform: translateY(-6px) scale(1.04);
          }
        }
        @keyframes tilt {
          0%,
          100% {
            transform: rotate(-2deg);
          }
          50% {
            transform: rotate(2deg);
          }
        }
        @keyframes talk {
          0%,
          100% {
            transform: scaleY(1);
          }
          50% {
            transform: scaleY(1.02);
          }
        }
        @keyframes jump {
          0%,
          100% {
            transform: translateY(0);
          }
          40% {
            transform: translateY(-14px);
          }
        }
        @keyframes wave {
          0%,
          100% {
            transform: rotate(0deg);
          }
          25% {
            transform: rotate(4deg);
          }
          75% {
            transform: rotate(-4deg);
          }
        }
      `}</style>
    </div>
  );
}
