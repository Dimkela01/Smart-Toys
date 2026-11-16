import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { SessionProvider } from '@/lib/session';
import './globals.css';

export const metadata: Metadata = {
  title: 'Bruno',
  description: 'A learning toy for children aged 3 to 10.',
  // no analytics, no third-party scripts (docs/CLAUDE.md §2)
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // the child screen must not be pinch-zoomed out of shape mid-session
  maximumScale: 5,
  themeColor: '#f7f6f3',
};

export default function RootLayout({ children }: { children: ReactNode }): ReactNode {
  // lang is set per subtree by the locale provider; html keeps the parent default
  return (
    <html lang="sr">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
