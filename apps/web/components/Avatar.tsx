'use client';

/* eslint-disable @next/next/no-img-element -- plain <img> keeps the placeholder SVGs
   unoptimised and swappable; see docs/CLAUDE.md §3 */

import type { ReactNode } from 'react';

/**
 * A child's sign-in picture. The file name comes from content/avatars.json, so real
 * artwork can replace it without touching the database.
 */
export function Avatar({
  avatarId,
  label,
  size = 120,
}: {
  avatarId: string;
  label: string;
  size?: number;
}): ReactNode {
  return (
    <img
      src={`/avatars/${avatarId}.svg`}
      alt={label}
      width={size}
      height={size}
      className="rounded-2xl"
      style={{ width: size, height: size }}
      draggable={false}
    />
  );
}
