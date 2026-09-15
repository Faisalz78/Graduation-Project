import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const qa = path.join(root, ".local/qa");

async function setup(page: Page, name = "ar-01-digital.pdf") {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill("employee@demo.test");
  await page.getByLabel("كلمة المرور", { exact: true }).fill(state.demo_password);
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const headers = { Origin: "http://127.0.0.1:3000", "X-CSRF-Token": session.csrf_token };
  const projects = await (await page.request.get("/api/v1/projects")).json();
  const response = await page.request.post("/api/v1/invoices", {
    headers: { ...headers, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: projects[0].id,
      note: "فاتورة مصطنعة لاختبار الاستخراج فقط.",
      file: {
        name: `تجريبي-${randomUUID().slice(0, 6)}-${name}`,
        mimeType: name.endsWith("pdf") ? "application/pdf" : "image/png",
        buffer: fs.readFileSync(path.join(root, "05_Data/Sample_Invoices/Synthetic_OCR_v1", name)),
      },
    },
  });
  expect(response.status()).toBe(201);
  const invoice = await response.json();
  await page.goto(`/invoices/${invoice.id}/edit`);
  await expect(
    page.getByRole("heading", { name: "استخراج بيانات الفاتورة", exact: true }),
  ).toBeVisible();
  return { invoice, headers };
}

async function read(page: Page) {
  const button = page.getByRole("button", { name: "استخراج البيانات", exact: true });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page.getByText("الاقتراحات جاهزة للمراجعة", { exact: true })).toBeVisible({
    timeout: 420000,
  });
}

test("local model failure is visible and preserves reviewable OCR suggestions", async ({
  page,
}) => {
  const { invoice } = await setup(page);
  await page.route(`**/api/v1/invoices/${invoice.id}/extraction`, async (route) => {
    await route.fulfill({
      json: {
        available: true,
        job: {
          id: randomUUID(),
          status: "SUCCEEDED",
          base_revision: invoice.revision,
          language: "ar",
          attempts: 1,
          is_stale: false,
          error: null,
          created_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          result: {
            fields: {
              invoice_number: {
                value: "FALLBACK-123",
                source: "PDF_TEXT",
                page: 1,
                bbox: [0.1, 0.1, 0.4, 0.15],
                confidence: null,
                evidence: "FALLBACK-123",
                needs_review: true,
              },
            },
            items: [],
            warnings: ["LOCAL_VISION_UNAVAILABLE"],
            requires_human_review: true,
            local_understanding: {
              status: "UNAVAILABLE",
              pages: 0,
              added_fields: 0,
              confirmed_fields: 0,
              added_rows: 0,
              conflicts: 0,
              rejected_values: 0,
              seconds: 1,
            },
          },
        },
      },
    });
  });
  await page.reload();
  await expect(page.getByLabel("الفهم البصري المحلي")).toContainText(
    "تعذر تشغيل الفهم البصري المحلي",
  );
  await expect(page.getByLabel("الفهم البصري المحلي")).not.toContainText(
    "اكتمل الفهم البصري على جهازك",
  );
  await page.getByRole("button", { name: "FALLBACK-123", exact: true }).click();
  await expect(page.locator(".evidence-box")).toBeVisible();
  await expect(page.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue("");
});

test("real PDF extraction requires review, saves corrections and preserves the original", async ({
  page,
}) => {
  test.setTimeout(480000);
  const { invoice, headers } = await setup(page);
  await read(page);
  await expect(page.getByLabel("طريقة قراءة الصفحات")).toContainText("قراءة النص مباشرة من PDF");
  const extraction = await (
    await page.request.get(`/api/v1/invoices/${invoice.id}/extraction`)
  ).json();
  expect(extraction.job.result.reader_version).toBe("pymupdf-paddle-guided-v7");
  expect(extraction.job.result.local_understanding.status).toBe("COMPLETED");
  await expect(page.getByLabel("الفهم البصري المحلي")).toContainText(
    "اكتمل الفهم البصري على جهازك",
  );
  expect(extraction.job.result.tokens.length).toBeGreaterThan(0);
  expect(extraction.job.result.tokens[0].reading_order).toBe(1);
  expect(extraction.job.result.text).toContain("AR-2026-110");
  await expect(page.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue("");
  const preview = page.getByAltText("الفاتورة الأصلية مع موضع الدليل");
  await expect(preview).toBeVisible();
  await expect
    .poll(() => preview.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
  await page.getByRole("button", { name: /^AR-2026-110/ }).click();
  await expect(page.locator(".evidence-box")).toBeVisible();
  await page.getByRole("button", { name: "نقل الاقتراحات للحقول الفارغة" }).click();
  await expect(page.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue("AR-2026-110");
  await expect(page.getByLabel("الصافي قبل الضريبة", { exact: false })).toHaveValue(/\d/);
  await expect(page.getByLabel("إجمالي الضريبة", { exact: false })).toHaveValue(/\d/);
  await expect(page.getByLabel("الإجمالي المستحق", { exact: false })).toHaveValue(/\d/);
  await expect(page.getByLabel("المورد", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("وصف البند", { exact: true })).toHaveCount(2);
  const save = page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true });
  await expect(save).toBeDisabled();
  const supplierResponse = await page.request.post("/api/v1/suppliers", {
    headers,
    data: { name: `مورد استخراج تجريبي ${randomUUID().slice(0, 6)}` },
  });
  expect(supplierResponse.status()).toBe(201);
  // The supplier remains a deliberate user choice; partial draft save is also supported.
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill("USER-CORRECTED-110");
  await page.getByLabel("راجعت الحقول والبنود المقترحة", { exact: false }).check();
  await expect(save).toBeEnabled();
  fs.mkdirSync(qa, { recursive: true });
  await page.screenshot({ path: path.join(qa, "extraction-pdf-review.png"), fullPage: true });
  await save.click();
  await expect(page).toHaveURL(new RegExp(`/invoices/${invoice.id}\\?updated=1`));
  const stored = await (await page.request.get(`/api/v1/invoices/${invoice.id}`)).json();
  expect(stored.invoice_number).toBe("USER-CORRECTED-110");
  expect(stored.items).toHaveLength(2);
  expect(
    stored.events.some((event: { action: string }) => event.action === "EXTRACTION_REVIEWED"),
  ).toBeTruthy();
  const original = await page.request.get(invoice.attachment.url);
  expect(await original.body()).toEqual(
    fs.readFileSync(path.join(root, "05_Data/Sample_Invoices/Synthetic_OCR_v1/ar-01-digital.pdf")),
  );
});

test("regional conflicts show both evidence locations without changing the editor", async ({
  page,
}) => {
  const { invoice } = await setup(page);
  const current = {
    value: "100.00",
    source: "OCR",
    page: 1,
    bbox: [0.1, 0.2, 0.4, 0.25],
    confidence: 0.93,
    evidence: "Grand total 100.00",
    needs_review: true,
  };
  const proposed = {
    ...current,
    value: "115.00",
    evidence: "Grand total 115.00",
    bbox: [0.5, 0.7, 0.8, 0.75],
  };
  await page.route(`**/api/v1/invoices/${invoice.id}/extraction`, (route) =>
    route.fulfill({
      json: {
        available: true,
        job: {
          id: randomUUID(),
          status: "SUCCEEDED",
          base_revision: invoice.revision,
          language: "ar",
          attempts: 1,
          is_stale: false,
          error: null,
          created_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          result: {
            fields: { grand_total: current },
            items: [],
            warnings: ["LOCAL_VISION_DISAGREEMENT"],
            requires_human_review: true,
            guided_reading: {
              status: "PARTIAL",
              attempted: 2,
              completed: 1,
              table_sections: 1,
              recovered_tokens: 3,
            },
            conflict_details: [
              { field: "grand_total", row: null, reason: "DISAGREEMENT", current, proposed },
            ],
          },
        },
      },
    }),
  );
  await page.reload();
  await expect(page.getByLabel("قراءة أجزاء الفاتورة")).toContainText(
    "لم تكتمل قراءة جميع الأجزاء",
  );
  const comparison = page.getByLabel("مقارنة القراءات المختلفة");
  await comparison.getByRole("button", { name: "100.00", exact: true }).click();
  await expect(page.locator(".evidence-text")).toContainText("Grand total 100.00");
  await comparison.getByRole("button", { name: "115.00", exact: true }).click();
  await expect(page.locator(".evidence-text")).toContainText("Grand total 115.00");
  await expect(page.locator(".evidence-box")).toHaveCSS("left", /\d/);
  await expect(page.getByLabel("الإجمالي المستحق", { exact: false })).toHaveValue("");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(comparison).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
  await page.screenshot({ path: path.join(qa, "guided-conflict-review.png"), fullPage: true });
});

test("real Arabic OCR preserves typed values and shows image evidence on mobile", async ({
  page,
}) => {
  test.setTimeout(480000);
  await setup(page, "ar-02-scan.png");
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill("KEEP-MY-EDIT");
  await read(page);
  await expect(page.getByLabel("طريقة قراءة الصفحات")).toContainText("قراءة من الصورة");
  await page.getByRole("button", { name: /^AR-2026-111/ }).click();
  await expect(page.locator(".evidence-box")).toBeVisible();
  await page.getByRole("button", { name: "نقل الاقتراحات للحقول الفارغة" }).click();
  await expect(page.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue("KEEP-MY-EDIT");
  await expect(page.getByLabel("تاريخ الفاتورة", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".evidence-box")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
  await page.screenshot({ path: path.join(qa, "extraction-arabic-mobile.png"), fullPage: true });
});

test("a newer saved revision blocks an old extraction review without losing edits", async ({
  page,
}) => {
  test.setTimeout(480000);
  const { invoice, headers } = await setup(page);
  await read(page);
  await page.getByRole("button", { name: "نقل الاقتراحات للحقول الفارغة" }).click();
  const update = await page.request.put(`/api/v1/invoices/${invoice.id}`, {
    headers,
    data: {
      revision: invoice.revision,
      supplier_id: null,
      invoice_number: "NEWER-SAVED",
      invoice_date: null,
      currency: null,
      note: "تعديل أحدث تجريبي",
      items: [],
    },
  });
  expect(update.status()).toBe(200);
  await page.getByLabel("راجعت الحقول والبنود المقترحة", { exact: false }).check();
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "حُفظت نسخة أحدث" })).toBeVisible();
  await expect(page.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue("AR-2026-110");
  const current = await (await page.request.get(`/api/v1/invoices/${invoice.id}`)).json();
  expect(current.invoice_number).toBe("NEWER-SAVED");
});

test("rereading a successful extraction creates fresh suggestions and keeps typed edits", async ({
  page,
}) => {
  test.setTimeout(480000);
  const { invoice } = await setup(page);
  await read(page);
  const first = (await (await page.request.get(`/api/v1/invoices/${invoice.id}/extraction`)).json())
    .job;
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill("KEEP-UNSAVED");
  // The server's enqueue cooldown applies to deliberate rereads as well.
  await page.waitForTimeout(Math.max(0, 11000 - (Date.now() - Date.parse(first.created_at))));
  await page.getByRole("button", { name: "إعادة قراءة الفاتورة", exact: true }).click();
  await expect
    .poll(
      async () => {
        const job = (
          await (await page.request.get(`/api/v1/invoices/${invoice.id}/extraction`)).json()
        ).job;
        return job.id !== first.id && job.status === "SUCCEEDED";
      },
      { timeout: 420000 },
    )
    .toBeTruthy();
  await expect(page.getByText("الاقتراحات جاهزة للمراجعة", { exact: true })).toBeVisible();
  await expect(page.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue("KEEP-UNSAVED");
  const stored = await (await page.request.get(`/api/v1/invoices/${invoice.id}`)).json();
  expect(stored.revision).toBe(invoice.revision);
  expect(stored.invoice_number).toBeNull();
});
