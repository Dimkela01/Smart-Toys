import { expect, type Page } from '@playwright/test';

/**
 * Shared setup for the end-to-end run-throughs.
 *
 * Both the M1 journey and the M2 voice loop need the same beginning - a verified parent
 * with a PIN and a child - so it lives here rather than being written twice.
 *
 * Mail is read from Mailpit, so the verification link is followed exactly as a parent
 * would follow it.
 */

const MAILPIT = process.env.MAILPIT_API ?? 'http://localhost:8026/api/v1';
export const PASSWORD = 'dovoljno-duga-sifra';
export const PIN = '4821';

export function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 1000)}@example.com`;
}

export async function linkFromLatestEmail(page: Page, address: string): Promise<string> {
  // Mailpit needs a moment to receive the message
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const list = await page.request.get(`${MAILPIT}/search?query=${encodeURIComponent(address)}`);
    if (list.ok()) {
      const body = (await list.json()) as { messages?: { ID: string }[] };
      const id = body.messages?.[0]?.ID;
      if (id) {
        const message = await page.request.get(`${MAILPIT}/message/${id}`);
        const text = ((await message.json()) as { Text?: string }).Text ?? '';
        const found = /https?:\/\/\S+token=[A-Za-z0-9._-]+/.exec(text);
        if (found) return found[0];
      }
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`no verification link for ${address}`);
}

export async function registerAndVerify(page: Page, address: string): Promise<void> {
  await page.goto('/register');
  await page.getByLabel('Email adresa').fill(address);
  await page.getByLabel('Šifra').fill(PASSWORD);
  await page.getByRole('checkbox').first().check();
  await page.getByRole('checkbox').nth(1).check();
  await page.getByRole('button', { name: 'Napravi račun' }).click();
  await expect(page.getByRole('heading', { name: 'Proverite email' })).toBeVisible();

  const link = await linkFromLatestEmail(page, address);
  await page.goto(new URL(link).pathname + new URL(link).search);
  await expect(page.getByRole('heading', { name: 'Adresa je potvrđena' })).toBeVisible();
}

export async function setPin(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Postavi PIN' }).click();
  // the dev server may still be compiling /pin on a cold container
  await page.waitForURL('**/pin');
  await page.getByLabel('PIN', { exact: true }).fill(PIN);
  await page.getByLabel('Ponovite PIN').fill(PIN);
  await page.getByRole('button', { name: 'Sačuvaj PIN' }).click();
  await expect(page.getByRole('heading', { name: 'Vaša deca' })).toBeVisible();
}

export async function addChild(page: Page, nickname: string, avatarLabel: string): Promise<void> {
  await page.getByRole('button', { name: 'Dodaj dete' }).click();
  await expect(page.getByRole('heading', { name: 'Ko je dete?' })).toBeVisible();

  await page.getByLabel('Nadimak').fill(nickname);
  await page.getByRole('button', { name: '6', exact: true }).click();
  await page.getByRole('button', { name: 'Srpski' }).click();
  await page.getByRole('button', { name: 'Dalje' }).click();

  await expect(page.getByRole('heading', { name: 'Šta voli i koja je slika?' })).toBeVisible();
  await page.getByRole('button', { name: 'Životinje' }).click();
  await page.getByRole('button', { name: avatarLabel }).click();
  await page.getByRole('button', { name: 'Dalje' }).click();

  await expect(page.getByRole('heading', { name: 'Koji lik?' })).toBeVisible();
  await page.getByRole('button', { name: 'Bruno' }).click();
  await page.getByRole('button', { name: 'Napravi profil' }).click();

  await expect(page.getByRole('heading', { name: nickname })).toBeVisible();
}
