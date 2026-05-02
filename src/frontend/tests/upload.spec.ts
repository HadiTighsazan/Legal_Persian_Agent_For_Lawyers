import { test, expect, Page, BrowserContext } from '@playwright/test';

/**
 * Helper: bypass authentication by injecting localStorage tokens before
 * the page loads (via addInitScript) and mocking the /api/users/me/
 * endpoint so initializeAuth() succeeds.
 *
 * We use addInitScript instead of page.evaluate because localStorage
 * cannot be accessed on about:blank before navigation.
 */
async function bypassAuth(context: BrowserContext, page: Page) {
  // Inject localStorage tokens before any page script runs
  await context.addInitScript(() => {
    localStorage.setItem('access_token', 'fake-test-token');
    localStorage.setItem('refresh_token', 'fake-refresh-token');
  });

  // Mock GET /api/users/me/ so initializeAuth() resolves successfully
  await page.route('**/api/users/me/', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'test-user-id',
        email: 'test@example.com',
        username: 'testuser',
      }),
    });
  });
}

/**
 * Helper: create a minimal valid PDF buffer for file selection tests.
 */
function createMinimalPdfBuffer(): Buffer {
  // Minimal PDF that starts with %PDF-1.4 header
  return Buffer.from(
    '%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF'
  );
}

/**
 * Helper: create a dummy text file buffer.
 */
function createTextFileBuffer(): Buffer {
  return Buffer.from('This is a plain text file, not a PDF.', 'utf-8');
}

test.describe('T01 — Document Upload Flow', () => {
  test.beforeEach(async ({ context, page }) => {
    await bypassAuth(context, page);
    await page.goto('/documents/upload');
  });

  test('Upload button is disabled when no file or title is provided', async ({ page }) => {
    // Arrange — the page is already loaded at /documents/upload
    const uploadButton = page.getByRole('button', { name: /upload/i });

    // Assert — initially disabled (no title, no file)
    await expect(uploadButton).toBeDisabled();

    // Act — type a title but still no file
    await page.getByLabel(/document title/i).fill('My Test Document');

    // Assert — still disabled because no file is selected
    await expect(uploadButton).toBeDisabled();

    // Act — select a PDF file
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'test-document.pdf',
      mimeType: 'application/pdf',
      buffer: createMinimalPdfBuffer(),
    });

    // Assert — button becomes enabled
    await expect(uploadButton).toBeEnabled();
  });

  test('Invalid file selection shows error for non-PDF', async ({ page }) => {
    // Arrange — navigate to upload page

    // Act — select a .txt file
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'notes.txt',
      mimeType: 'text/plain',
      buffer: createTextFileBuffer(),
    });

    // Assert — error message is visible
    await expect(page.getByText('Only PDF files are allowed.')).toBeVisible();

    // Assert — no file preview is shown (the upload icon should still be visible)
    await expect(page.getByText(/drag & drop your pdf/i)).toBeVisible();
  });

  test('Valid PDF file selection shows file preview', async ({ page }) => {
    // Arrange — navigate to upload page

    // Act — select a valid PDF file
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'annual-report.pdf',
      mimeType: 'application/pdf',
      buffer: createMinimalPdfBuffer(),
    });

    // Assert — file name is displayed in the DropZone
    await expect(page.getByText('annual-report.pdf')).toBeVisible();

    // Assert — file size is displayed (the minimal PDF is tiny, ~0.00 MB)
    await expect(page.getByText(/mb/i)).toBeVisible();

    // Assert — no error message is shown
    await expect(page.getByText('Only PDF files are allowed.')).not.toBeVisible();
  });

  test('Successful upload flow with mocked API', async ({ page }) => {
    // Arrange — mock the upload endpoint with a slight delay so the
    // progress bar has time to render before the response resolves
    const mockResponse = {
      id: 'doc-123',
      title: 'Test',
      original_filename: 'test.pdf',
      file_size: 1024,
      total_pages: null,
      status: 'uploaded',
      created_at: new Date().toISOString(),
    };

    await page.route('**/api/documents/upload/', async (route) => {
      // Artificial delay so the uploading state is visible
      await new Promise((r) => setTimeout(r, 500));
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(mockResponse),
      });
    });

    // Act — fill in title and select a PDF file
    await page.getByLabel(/document title/i).fill('Test');
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'test.pdf',
      mimeType: 'application/pdf',
      buffer: createMinimalPdfBuffer(),
    });

    // Click Upload button
    const uploadButton = page.getByRole('button', { name: /upload/i });
    await uploadButton.click();

    // Assert — progress bar appears (Radix Progress renders with role="progressbar")
    await expect(page.getByRole('progressbar')).toBeVisible();

    // Assert — redirect to /documents/doc-123
    await page.waitForURL('**/documents/doc-123');
  });

  test('Upload error shows toast and stays on page', async ({ page }) => {
    // Arrange — mock the upload endpoint to return 500
    await page.route('**/api/documents/upload/', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    // Act — fill in title and select a PDF file
    await page.getByLabel(/document title/i).fill('Test');
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'test.pdf',
      mimeType: 'application/pdf',
      buffer: createMinimalPdfBuffer(),
    });

    // Click Upload button
    const uploadButton = page.getByRole('button', { name: /upload/i });
    await uploadButton.click();

    // Assert — error toast with "Server error" is visible
    // Radix Toast renders with role="status"
    const toast = page.getByRole('status');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText('Server error');

    // Assert — URL is still /documents/upload
    await expect(page).toHaveURL(/\/documents\/upload/);
  });
});
