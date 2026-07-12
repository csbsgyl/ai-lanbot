import { expect, test } from '@playwright/test';

import { installLangBotApiMocks } from './fixtures/langbot-api';

const appRoutes = [
  {
    path: '/home/bots',
    heading: 'Bots',
    bodyText: 'Select a bot from the sidebar',
  },
  {
    path: '/home/pipelines',
    heading: 'Pipelines',
    bodyText: 'Select a pipeline from the sidebar',
  },
  {
    path: '/home/extensions',
    heading: 'Extensions',
    bodyText: 'No extensions installed',
  },
  {
    path: '/home/mcp',
    heading: 'MCP',
    bodyText: 'Select an MCP server from the sidebar',
  },
  {
    path: '/home/knowledge',
    heading: 'Knowledge',
    bodyText: 'Select a knowledge base from the sidebar',
  },
];

test.describe('authenticated app shell', () => {
  for (const route of appRoutes) {
    test(`${route.path} renders without a backend process`, async ({
      page,
    }) => {
      await installLangBotApiMocks(page, { authenticated: true });

      await page.goto(route.path);

      await expect(page).toHaveURL(new RegExp(`${route.path}$`));
      await expect(page.getByText('Home').first()).toBeVisible();
      await expect(
        page.getByRole('button', { name: 'Dashboard' }),
      ).toBeVisible();
      await expect(page.getByText('Extensions').first()).toBeVisible();
      await expect(page.getByText(route.heading).first()).toBeVisible();
      await expect(page.getByText(route.bodyText)).toBeVisible();
      await expect(page.getByText('Backend unavailable')).toHaveCount(0);
    });
  }

  test('/home/monitoring loads dashboard data from mocked APIs', async ({
    page,
  }) => {
    await installLangBotApiMocks(page, { authenticated: true });

    await page.goto('/home/monitoring');

    await expect(page).toHaveURL(/\/home\/monitoring$/);
    await expect(page.getByText('Total Messages').first()).toBeVisible();
    await expect(
      page.getByRole('tab', { name: 'Message Records' }),
    ).toBeVisible();
    await expect(
      page.getByRole('tab', { name: 'Token Monitoring' }),
    ).toBeVisible();

    await page.getByRole('tab', { name: 'Token Monitoring' }).click();
    await expect(
      page.getByText('No token usage in the selected time range'),
    ).toBeVisible();
    await expect(page.getByText('Unable to connect to server')).toHaveCount(0);
  });

  test('/home/extensions shows plugin debug information from the backend', async ({
    page,
  }) => {
    await installLangBotApiMocks(page, { authenticated: true });

    await page.goto('/home/extensions');

    await page.getByRole('button', { name: 'Debug Info' }).click();

    await expect(page.getByText('Plugin Debug Information')).toBeVisible();
    await expect(page.getByRole('textbox').nth(0)).toHaveValue(
      'ws://127.0.0.1:5300/plugin/debug',
    );
    await expect(page.getByRole('textbox').nth(1)).toHaveValue(
      'test-debug-key',
    );
  });

  test('sidebar update control opens the managed update flow', async ({
    page,
  }) => {
    await installLangBotApiMocks(page, { authenticated: true });

    await page.goto('/home/bots');
    await page.getByRole('button', { name: 'Manage updates' }).click();

    await expect(
      page.getByRole('heading', { name: 'Software Update' }),
    ).toBeVisible();
    await expect(page.getByText('11111111')).toBeVisible();
    await expect(page.getByText('22222222')).toBeVisible();
    await expect(page.getByText('Update available')).toBeVisible();

    await page.getByRole('button', { name: 'Update now' }).click();
    await expect(
      page.getByRole('heading', { name: 'Install update?' }),
    ).toBeVisible();
    await page
      .getByRole('alertdialog')
      .getByRole('button', { name: 'Update now' })
      .click();
    await expect(page.getByText('Update request submitted')).toBeVisible();
  });

  test('managed update flow fits a mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await installLangBotApiMocks(page, { authenticated: true });

    await page.goto('/home/bots');
    await page.getByRole('button', { name: 'Toggle Sidebar' }).click();
    await page.getByRole('button', { name: 'Manage updates' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole('button', { name: 'Check for updates' }),
    ).toBeVisible();
    await expect(
      dialog.getByRole('button', { name: 'Update now' }),
    ).toBeVisible();

    const bounds = await dialog.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844);
  });

  test('IDC query settings save credentials without returning the token', async ({
    page,
  }) => {
    await installLangBotApiMocks(page, { authenticated: true });

    await page.goto('/home/bots');
    await page.getByRole('button', { name: 'IDC Query' }).first().click();

    const dialog = page.getByRole('dialog');
    await expect(
      dialog.getByRole('heading', { name: 'IDC Query' }),
    ).toBeVisible();
    await expect(dialog.getByText('Gateway not configured')).toBeVisible();

    await dialog
      .getByLabel('Gateway URL')
      .fill('https://query.example.com/api/');
    await dialog.getByLabel('Request timeout').fill('15');
    await dialog.getByLabel('Queries per member / minute').fill('25');
    await dialog
      .getByLabel('Binding attempts per member / 10 minutes')
      .fill('3');
    await dialog.getByLabel('Service token').fill('playwright-secret-token');
    await dialog.getByRole('button', { name: 'Save' }).click();

    await expect(page.getByText('IDC query settings saved')).toBeVisible();
    await expect(dialog.getByText('Gateway configured')).toBeVisible();
    await expect(dialog.getByLabel('Gateway URL')).toHaveValue(
      'https://query.example.com/api',
    );
    await expect(dialog.getByLabel('Service token')).toHaveValue('');
    await expect(dialog.getByText('Configured').last()).toBeVisible();
    await expect(dialog.getByLabel('Queries per member / minute')).toHaveValue(
      '25',
    );

    await dialog.getByRole('tab', { name: 'Recent activity' }).click();
    await expect(dialog.getByText('IP query')).toBeVisible();
    await expect(dialog.getByText('Success')).toBeVisible();
    await expect(dialog.getByText('Balance')).toBeVisible();
    await expect(dialog.getByText('Denied')).toBeVisible();
    await expect(dialog).toContainText('qq-***90');
    await expect(dialog).toContainText('1***6');
    await expect(dialog).not.toContainText('qq-group-openid-1234567890');
    await expect(dialog).not.toContainText('qq-member-openid-1234567890');
    await expect(dialog).not.toContainText('10086');

    await dialog.getByRole('tab', { name: 'Configuration' }).click();

    await dialog.getByRole('button', { name: 'Clear token' }).click();
    await expect(
      dialog.getByText('The current service token will be cleared on save.'),
    ).toBeVisible();
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(dialog.getByText('Not configured')).toBeVisible();
  });

  test('IDC query settings fit a mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await installLangBotApiMocks(page, { authenticated: true });

    await page.goto('/home/bots');
    await page.getByRole('button', { name: 'Toggle Sidebar' }).click();
    await page.getByRole('button', { name: 'IDC Query' }).first().click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Gateway URL')).toBeVisible();
    await expect(dialog.getByLabel('Request timeout')).toBeVisible();
    await expect(dialog.getByLabel('Service token')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Save' })).toBeVisible();

    const bounds = await dialog.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844);
  });

  test('/home/skills?action=create creates a manual skill', async ({
    page,
  }) => {
    await installLangBotApiMocks(page, { authenticated: true });

    await page.goto('/home/skills?action=create');

    await expect(page).toHaveURL(/\/home\/skills\?action=create$/);
    await expect(page.getByText('Create Skill').first()).toBeVisible();
    await expect(page.getByText('Import Local Skill Directory')).toBeVisible();

    const saveButton = page.getByRole('button', { name: 'Save' });
    await expect(saveButton).toBeEnabled();
    await saveButton.click();
    await expect(page.getByText('Skill name cannot be empty')).toBeVisible();

    await page.locator('#display_name').fill('Daily Summary');
    await page.locator('#name').fill('daily_summary');
    await page
      .locator('#description')
      .fill('Summarizes the current conversation for handoff.');
    await page
      .locator('#instructions')
      .fill('Summarize the conversation in five concise bullet points.');
    await saveButton.click();

    await expect(page).toHaveURL(/\/home\/skills\?id=daily_summary$/);
    await expect(
      page.getByRole('heading', { name: 'Daily Summary' }),
    ).toBeVisible();
    await expect(page.locator('#name')).toHaveValue('daily_summary');
    await expect(page.locator('#description')).toHaveValue(
      'Summarizes the current conversation for handoff.',
    );
    await expect(page.locator('#instructions')).toHaveValue(
      'Summarize the conversation in five concise bullet points.',
    );
  });
});
