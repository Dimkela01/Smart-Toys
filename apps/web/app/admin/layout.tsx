import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Bruno admin',
  robots: { index: false, follow: false },
};

/**
 * Admin layout (UI.md §6): plain tables, desktop is fine, never linked from parent pages.
 * In deployment it also sits behind a separate host or an IP allow-list (ARCHITECTURE.md §9).
 */
export default function AdminLayout({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="min-h-dvh bg-white">
      <div className="mx-auto w-full max-w-4xl px-5 py-8">{children}</div>
    </div>
  );
}
