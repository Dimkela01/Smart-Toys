import { expect, test } from '@playwright/test';
import { addChild, registerAndVerify, setPin, uniqueEmail } from './helpers';

/**
 * The voice half of the quality-bar journey (docs/CLAUDE.md §5, F-05, UC-11, UC-22):
 *
 *   hand the phone over -> pick the picture -> hold the paw -> the pipeline runs ->
 *   and nothing textual ever appears on the child's screen
 *
 * **The microphone is synthesized in the page, not captured.** Playwright's Chromium has
 * no audio capture on this platform: every form of getUserMedia, down to `{audio: true}`,
 * answers NotSupportedError, with or without --use-fake-device-for-media-stream. So the
 * init script below replaces getUserMedia with a real MediaStream fed by an oscillator.
 * Everything after that point is the genuine article - the worklet, the resampling, the
 * 20 ms frames, the socket, the server pipeline, the error code and the recorded
 * fallback line. Only the device itself is stood in for.
 *
 * A tone is not speech, so the server's speech-to-text finds nothing to transcribe and
 * the turn ends through `stt_empty`. That is the path worth asserting here anyway: a
 * failure must be *heard* and never shown.
 *
 * That Bruno answers *real* speech is measured by `make bench`, which drives this same
 * socket with synthesized questions: 40 of 40 turns answered, p50 under 3 s.
 */

/** A MediaStream made in the page, so no capture device is needed. */
const FAKE_MICROPHONE = `
  const context = new AudioContext();
  const destination = context.createMediaStreamDestination();
  const oscillator = context.createOscillator();
  oscillator.frequency.value = 220;
  const level = context.createGain();
  level.gain.value = 0.2;
  oscillator.connect(level);
  level.connect(destination);
  oscillator.start();
  navigator.mediaDevices.getUserMedia = async () => destination.stream;
`;

test.use({
  permissions: ['microphone'],
  launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] },
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(FAKE_MICROPHONE);
});

test.describe('M2 voice loop', () => {
  test('holding the paw runs a whole turn and the child is never shown words', async ({ page }) => {
    // Uncaught exceptions, not console errors: the app legitimately logs a 401 from
    // /auth/refresh before anyone has signed in, and a test that failed on that would
    // only teach people to delete it.
    const crashes: string[] = [];
    page.on('pageerror', (error) => crashes.push(error.message));

    await test.step('get to the toy screen', async () => {
      await registerAndVerify(page, uniqueEmail());
      await setPin(page);
      await addChild(page, 'Mina', 'Sova');
      await page.getByRole('button', { name: 'Daj detetu' }).click();
      await page.waitForURL('**/child');
      await page.getByRole('button', { name: 'Mina' }).click();
      await page.waitForURL('**/child/toy');
    });

    const paw = page.getByRole('button', { name: 'Drži šapu i govori' });
    // The screen is not quite wordless: the English activity card carries an "ABC"
    // pictogram by design (UI.md §3.2), and a sleeping Bruno has a "z" over his head.
    // What must never appear is a *new* word - a transcript, an answer, an error - so
    // the test compares before with after rather than asserting emptiness. The snapshot
    // is taken once Bruno is awake, or the "z" alone would fail it.
    let before = '';

    await test.step('the paw becomes usable once the socket is open', async () => {
      // disabled until the WebSocket connects, so a press cannot be lost
      await expect(paw).toBeEnabled({ timeout: 20_000 });
      await expect(page.locator('.character--idle')).toBeVisible();
      before = (await page.locator('.child-screen').innerText()).trim();
    });

    await test.step('holding the paw sends audio and releasing it starts the turn', async () => {
      await paw.hover();
      await page.mouse.down();
      await expect(page.locator('.character--listening')).toBeVisible();
      // long enough to clear the 400 ms minimum, so this is a hold and not a tap
      await page.waitForTimeout(1200);
      await page.mouse.up();

      // the server takes over the character's state from here (UI.md §3.3)
      await expect(page.locator('.character--thinking')).toBeVisible({ timeout: 10_000 });
    });

    await test.step('the turn ends and Bruno settles back down', async () => {
      await expect(page.locator('.character--idle')).toBeVisible({ timeout: 30_000 });
    });

    await test.step('the turn added no words to the screen', async () => {
      const after = (await page.locator('.child-screen').innerText()).trim();
      expect(after).toBe(before);
      expect(crashes).toEqual([]);
    });
  });

  test('a tap instead of a hold is answered, not ignored', async ({ page }) => {
    await registerAndVerify(page, uniqueEmail());
    await setPin(page);
    await addChild(page, 'Mina', 'Sova');
    await page.getByRole('button', { name: 'Daj detetu' }).click();
    await page.waitForURL('**/child');
    await page.getByRole('button', { name: 'Mina' }).click();
    await page.waitForURL('**/child/toy');

    const paw = page.getByRole('button', { name: 'Drži šapu i govori' });
    await expect(paw).toBeEnabled({ timeout: 20_000 });
    const before = (await page.locator('.child-screen').innerText()).trim();

    // a press under 400 ms carries no speech; the child hears "hold the paw" (UC-22)
    await paw.click();
    await expect(page.locator('.character--idle')).toBeVisible({ timeout: 15_000 });
    const after = (await page.locator('.child-screen').innerText()).trim();
    expect(after).toBe(before);
  });
});
