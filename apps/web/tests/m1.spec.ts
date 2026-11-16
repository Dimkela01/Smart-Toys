import { expect, test, type Page } from '@playwright/test';

/**
 * The M1 run-through from the quality bar (docs/CLAUDE.md §5), at 360x740:
 *
 *   register -> verify by email -> set PIN -> add child -> child mode ->
 *   pick picture -> toy screen -> exit with the corner press and the PIN -> dashboard
 *
 * The "hold paw, hear an answer" part of that journey needs the voice pipeline and is
 * added in M2; here the paw only has to move the character.
 *
 * Mail is read from Mailpit, so the verification link is followed exactly as a parent
 * would follow it.
 */

const MAILPIT = process.env.MAILPIT_API ?? 'http://localhost:8026/api/v1';
const PASSWORD = 'dovoljno-duga-sifra';
const PIN = '4821';

function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 1000)}@example.com`;
}

async function linkFromLatestEmail(page: Page, address: string): Promise<string> {
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

async function registerAndVerify(page: Page, address: string): Promise<void> {
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

async function setPin(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Postavi PIN' }).click();
  // the dev server may still be compiling /pin on a cold container
  await page.waitForURL('**/pin');
  await page.getByLabel('PIN', { exact: true }).fill(PIN);
  await page.getByLabel('Ponovite PIN').fill(PIN);
  await page.getByRole('button', { name: 'Sačuvaj PIN' }).click();
  await expect(page.getByRole('heading', { name: 'Vaša deca' })).toBeVisible();
}

async function addChild(page: Page, nickname: string, avatarLabel: string): Promise<void> {
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

test.describe('M1 run-through', () => {
  test('a parent can register, add a child, hand the phone over and take it back', async ({
    page,
  }) => {
    const address = uniqueEmail();

    await test.step('register and confirm the address', async () => {
      await registerAndVerify(page, address);
    });

    await test.step('set the parent PIN', async () => {
      await setPin(page);
    });

    await test.step('the dashboard asks for a child before handing over', async () => {
      await expect(page.getByRole('heading', { name: 'Još nema profila' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Daj detetu' })).toBeDisabled();
    });

    await test.step('add a child profile with the UC-04 defaults', async () => {
      await addChild(page, 'Mina', 'Sova');
      await expect(page.getByText('20 min dnevno')).toBeVisible();
      await expect(page.getByText('od 07:00 do 20:30')).toBeVisible();
      // transcripts are off by default (D3)
      await expect(page.getByText('vidite sažetke')).toBeVisible();
    });

    await test.step('give the phone to the child and pick the picture', async () => {
      await page.getByRole('button', { name: 'Daj detetu' }).click();
      await page.waitForURL('**/child');
      const picture = page.getByRole('button', { name: 'Mina' });
      await expect(picture).toBeVisible();
      // the picker needs no reading and the pictures are large (UI.md §3.1)
      const box = await picture.boundingBox();
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(120);
      await picture.click();
      await page.waitForURL('**/child/toy');
    });

    await test.step('the toy screen shows the character, the paw and the activities', async () => {
      await expect(page.getByRole('img', { name: 'Mina' })).toBeVisible();
      const paw = page.getByRole('button', { name: 'Drži šapu i govori' });
      await expect(paw).toBeVisible();
      const box = await paw.boundingBox();
      // the paw is at least 96 px (UI.md §3.2)
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(96);
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(96);

      for (const name of ['Pitanja', 'Priča', 'Brojevi', 'Engleski']) {
        await expect(page.getByRole('button', { name })).toBeVisible();
      }

      // holding the paw moves the character; no text ever appears for the child
      await paw.hover();
      await page.mouse.down();
      await expect(page.locator('.character--listening')).toBeVisible();
      await page.mouse.up();
      await expect(page.locator('.character--idle')).toBeVisible();

      // tapping a card is acknowledged, then Bruno settles back down rather than
      // celebrating for ever
      await page.getByRole('button', { name: 'Brojevi' }).click();
      await expect(page.locator('.character--happy')).toBeVisible();
      await expect(page.locator('.character--idle')).toBeVisible({ timeout: 5000 });
    });

    await test.step('child mode is locked: back does not leave it', async () => {
      await page.goBack();
      await page.waitForTimeout(300);
      expect(new URL(page.url()).pathname).toBe('/child/toy');
    });

    await test.step('a wrong PIN does not open the exit', async () => {
      await page.mouse.move(8, 8);
      await page.mouse.down();
      await page.waitForTimeout(3200);
      await page.mouse.up();

      await expect(page.getByRole('heading', { name: 'Unesite PIN' })).toBeVisible();
      for (const digit of ['0', '0', '0', '0']) {
        await page.getByRole('button', { name: digit, exact: true }).click();
      }
      await expect(page.getByText('PIN nije tačan.')).toBeVisible();
    });

    await test.step('the right PIN returns the parent to the dashboard', async () => {
      for (const digit of PIN.split('')) {
        await page.getByRole('button', { name: digit, exact: true }).click();
      }
      await page.waitForURL('**/dashboard');
      await expect(page.getByRole('heading', { name: 'Vaša deca' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Mina' })).toBeVisible();
    });
  });

  test('a child cannot be given the phone without a profile, and login routes by what is missing', async ({
    page,
  }) => {
    const address = uniqueEmail();
    await registerAndVerify(page, address);
    await setPin(page);

    // signing out and back in lands on the dashboard, because nothing is missing
    await page.getByRole('button', { name: 'Odjavi se' }).click();
    await page.waitForURL('**/login');

    await page.getByLabel('Email adresa').fill(address);
    await page.getByLabel('Šifra').fill(PASSWORD);
    await page.getByRole('button', { name: 'Prijavi se' }).click();
    await page.waitForURL('**/dashboard');
    await expect(page.getByRole('heading', { name: 'Vaša deca' })).toBeVisible();
  });

  test('a wrong password is refused and the message does not say which part was wrong', async ({
    page,
  }) => {
    const address = uniqueEmail();
    await registerAndVerify(page, address);

    await page.goto('/login');
    await page.getByLabel('Email adresa').fill(address);
    await page.getByLabel('Šifra').fill('wrong-password-here');
    await page.getByRole('button', { name: 'Prijavi se' }).click();
    await expect(page.getByText('Pogrešna email adresa ili šifra.')).toBeVisible();
  });

  test('the admin page is reachable and refuses a password without a code', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByRole('heading', { name: 'Administracija' })).toBeVisible();
    // deliberately an address that does not exist: repeated failures against the real
    // seeded admin would lock that account for 15 minutes and break the next run
    await page.getByLabel('Email adresa').fill(uniqueEmail());
    await page.getByLabel('Šifra').fill('admin_dev_password');
    await page.getByLabel('Kod iz aplikacije').fill('000000');
    await page.getByRole('button', { name: 'Prijavi se' }).click();
    await expect(page.getByText('Pogrešna adresa, šifra ili kod.')).toBeVisible();
  });
});
