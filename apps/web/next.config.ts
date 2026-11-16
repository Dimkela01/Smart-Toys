import type { NextConfig } from 'next';

/**
 * The browser talks to one origin only: the API is proxied through this app, so the
 * refresh cookie stays first-party (ARCHITECTURE.md §2) and no CORS is needed.
 */
const apiTarget = process.env.API_INTERNAL_URL ?? 'http://localhost:8001';

// No third-party scripts, styles, fonts or trackers anywhere (docs/CLAUDE.md §2).
// 'unsafe-inline'/'unsafe-eval' in script-src are required by the Next.js dev server;
// the production build in M7 tightens this to a nonce.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "media-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'none'",
  "form-action 'self'",
].join('; ');

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: '/api/v1/:path*', destination: `${apiTarget}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'Content-Security-Policy', value: csp },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'Permissions-Policy', value: 'geolocation=(), camera=(), payment=()' },
        ],
      },
    ];
  },
};

export default nextConfig;
