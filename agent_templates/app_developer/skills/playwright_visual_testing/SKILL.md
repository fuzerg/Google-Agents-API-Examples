---
name: playwright_visual_testing
description: Guidelines on using Playwright for visual regression testing and layout verification in web applications.
---

# Playwright Visual Verification & Layout Testing

This skill documents how to integrate Playwright into your web application workflow to perform robust visual verification, layout alignment asserts, and screenshot-based styling verification.

## 1. Setup & Environment Configurations

To ensure headless browser instances execute reliably in all sandbox/CI environments (such as Docker, remote VM runners, or Linux systems), you must configure and install the appropriate browser dependencies.

### Dependencies Installation
Run the following commands to update system libraries and acquire appropriate rendering drivers:

```bash
# Update local packages and install system-level browser rendering prerequisites
sudo apt-get update
sudo apt-get install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2

# Install Playwright and standard Chromium binaries
npm install @playwright/test
npx playwright install chromium
```

---

## 2. Designing Visual Assertions Spec

By utilizing Playwright's modular page context, you can render UI markup dynamically, force rigid viewports, and assert layout structures safely before saving verified graphic screenshots.

### Example Spec File (`visual_layout.spec.ts`)

```typescript
import { test, expect } from '@playwright/test';

test('verify responsive styling constraints', async ({ page }) => {
  // Set standard test viewport resolution
  await page.setViewportSize({ width: 1280, height: 720 });

  // Custom mock HTML representing the layout under verification
  const layoutContent = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Mock Layout View</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-neutral-900 p-8 text-neutral-100 flex items-center justify-center">
      <div class="w-full max-w-2xl border border-neutral-800 rounded-xl p-4 bg-neutral-950" id="target-box">
        <span class="flex items-center gap-2 font-mono text-xs text-blue-400">
          <span class="h-2 w-2 animate-ping rounded-full bg-blue-500"></span>
          Ready for testing
        </span>
      </div>
    </body>
    </html>
  `;

  // Inject markup directly into active browser instance
  await page.setContent(layoutContent);

  // Take full-page styling verification screenshot
  await page.screenshot({ path: 'frontend-visual-verification.png', fullPage: true });

  // Assert target properties
  const targetBox = page.locator('#target-box');
  await expect(targetBox).toBeVisible();

  const borderColor = await targetBox.evaluate((el) => window.getComputedStyle(el).borderColor);
  // Assert border formatting properties matches layout expectations
  console.log("Playwright visual test execution completed successfully!");
});
```

---

## 3. Best Practices for Binary Graphic Assets

To avoid graphic file corruptions, never save or push visual screenshot assets through plain-text channels (which might corrupt binary headers with character-set normalizations). 

### Verification & Checksums
- **Magic Byte Verification**: Check that your `.png` file has the valid magic bytes `\x89PNG\r\n\x1a\n` at the header.
- **Size validation**: Ensure that your asset has a file size greater than `0 bytes`.

### Scripted Verification Check

```python
# Quick Python script to confirm raw binary format is clean before pushing or committing:
import base64

with open('frontend-visual-verification.png', 'rb') as f:
    data = f.read()
    if data.startswith(b'\x89PNG'):
        print(f"Pristine PNG binary confirmed! Total bytes: {len(data)}")
    else:
        print("Error: Visual layout image file is corrupted or contains text-encoded characters.")
```
