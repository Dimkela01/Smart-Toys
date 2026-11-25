import { expect, test } from '@playwright/test';
import { PASSWORD, PIN, addChild, registerAndVerify, setPin, uniqueEmail } from './helpers';

/**
 * The M1 run-through from the quality bar (docs/CLAUDE.md §5), at 360x740:
 *
 *   register -> verify by email -> set PIN -> add child -> child mode ->
 *   pick picture -> toy screen -> exit with the corner press and the PIN -> dashboard
 *
 * The voice half of that journey - hold the paw, hear an answer - is m2.spec.ts.
 *
 * Setup helpers live in ./helpers, shared with the M2 run-through.
 */

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

      // What the paw then does with the microphone and the socket is m2.spec.ts.
      await expect(page.locator('.character--idle')).toBeVisible();

      // tapping a card is acknowledged, then Bruno settles back down rather than
      // celebrating for ever
      await page.getByRole('button', { name: 'Brojevi' }).click();
      await expect(page.locator('.character--happy')).toBeVisible();
      await expect(page.locator('.character--idle')).toBeVisible({ timeout: 5000 });
    });

    await test.step('the paw stays on screen in landscape', async () => {
      // the toy screen is fixed and never scrolls, so anything that does not fit is simply
      // unreachable: in landscape the paw was pushed off the bottom and disappeared
      await page.setViewportSize({ width: 740, height: 360 });
      await page.waitForTimeout(300);

      const paw = page.getByRole('button', { name: 'Drži šapu i govori' });
      await expect(paw).toBeVisible();
      const box = await paw.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y + box!.height).toBeLessThanOrEqual(360);
      expect(box!.height).toBeGreaterThanOrEqual(96);
      await expect(page.getByRole('button', { name: 'Brojevi' })).toBeVisible();

      await page.setViewportSize({ width: 360, height: 740 });
      await page.waitForTimeout(300);
      await expect(paw).toBeVisible();
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

  test('a second tab explains the lock and the PIN still gets the parent out', async ({
    context,
  }) => {
    const page = await context.newPage();
    const address = uniqueEmail();
    await registerAndVerify(page, address);
    await setPin(page);
    await addChild(page, 'Mina', 'Sova');
    await page.getByRole('button', { name: 'Daj detetu' }).click();
    await page.waitForURL('**/child');

    // a new tab shares the cookies but not sessionStorage, so it has no child-mode token
    const second = await context.newPage();
    const failures: string[] = [];
    second.on('pageerror', (error) => failures.push(error.message));

    await second.goto('/dashboard');
    await second.waitForTimeout(2500);

    await expect(second.getByRole('heading', { name: 'Dečji režim je uključen' })).toBeVisible();
    expect(failures).toEqual([]);
    // and it must not have handed a parent session to the new tab
    await expect(second.getByRole('heading', { name: 'Vaša deca' })).toBeHidden();

    // the explanation must not be a dead end: /child-mode/exit needs the token this tab
    // never had, so without /auth/unlock the parent could never use this device again
    await second.getByRole('button', { name: 'Unesite PIN' }).click();
    await expect(second.getByRole('heading', { name: 'Unesite PIN' })).toBeVisible();
    for (const digit of ['0', '0', '0', '0']) {
      await second.getByRole('button', { name: digit, exact: true }).click();
    }
    await expect(second.getByText('PIN nije tačan.')).toBeVisible();

    for (const digit of PIN.split('')) {
      await second.getByRole('button', { name: digit, exact: true }).click();
    }
    await second.waitForURL('**/dashboard');
    await expect(second.getByRole('heading', { name: 'Vaša deca' })).toBeVisible();

    await second.close();
    await page.close();
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
