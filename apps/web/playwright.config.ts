import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end run-through of M1 (docs/CLAUDE.md §5).
 *
 * The stack must be running (`make dev`). Ports come from .env, so the test suite follows
 * whatever the developer configured.
 */
const webPort = process.env.WEB_PORT ?? '3001';
const mailpitPort = process.env.MAILPIT_UI_PORT ?? '8026';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  timeout: 60_000,
  use: {
    baseURL: `http://localhost:${webPort}`,
    // every screen is checked at phone size (NFR-01, 360x740)
    viewport: { width: 360, height: 740 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    extraHTTPHeaders: {},
  },
  projects: [
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 7'], viewport: { width: 360, height: 740 } },
    },
  ],
  metadata: { mailpit: `http://localhost:${mailpitPort}` },
});
