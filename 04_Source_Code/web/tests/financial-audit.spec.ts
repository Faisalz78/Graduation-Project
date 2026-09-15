import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const sample = fs.readFileSync(path.join(root, ".local/samples/demo-invoice.pdf"));
const qa = path.join(root, ".local/qa");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill("employee@demo.test");
  await page.getByLabel("كلمة المرور", { exact: true }).fill(state.demo_password);
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
}

function uniquePdf() {
  const marker = sample.lastIndexOf(Buffer.from("startxref"));
  expect(marker).toBeGreaterThan(0);
  return Buffer.concat([
    sample.subarray(0, marker),
    Buffer.from(`% financial-audit-test ${randomUUID()}\n`),
    sample.subarray(marker),
  ]);
}

async function seedPriceHistory(
  page: Page,
  headers: Record<string, string>,
  projectId: string,
  supplierId: string,
) {
  for (const [index, price] of ["40", "45", "50"].entries()) {
    const upload = await page.request.post("/api/v1/invoices", {
      headers: { ...headers, "Idempotency-Key": randomUUID() },
      multipart: {
        project_id: projectId,
        note: "عينة مصطنعة لبناء مرجع الأسعار.",
        file: {
          name: `مرجع-سعر-${index + 1}.pdf`,
          mimeType: "application/pdf",
          buffer: uniquePdf(),
        },
      },
    });
    expect(upload.status()).toBe(201);
    const draft = await upload.json();
    const saved = await page.request.put(`/api/v1/invoices/${draft.id}`, {
      headers,
      data: {
        revision: draft.revision,
        supplier_id: supplierId,
        invoice_number: `PRICE-HISTORY-${index + 1}-${randomUUID().slice(0, 6)}`,
        invoice_date: `2026-08-0${index + 1}`,
        currency: "SAR",
        note: draft.note,
        document_totals: null,
        items: [
          {
            description: "مواد تدقيق تجريبية",
            unit: null,
            quantity: "2",
            unit_price: price,
            discount_amount: "0",
            tax_rate: "15",
          },
        ],
      },
    });
    expect(saved.status()).toBe(200);
    const ready = await saved.json();
    const submitted = await page.request.post(`/api/v1/invoices/${ready.id}/workflow`, {
      headers,
      data: { revision: ready.revision, action: "SUBMIT", confirmed: true },
    });
    expect(submitted.status()).toBe(200);
  }
}

test("document totals and duplicate findings stay visible and explainable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const headers = { Origin: "http://127.0.0.1:3000", "X-CSRF-Token": session.csrf_token };
  const project = (await (await page.request.get("/api/v1/projects")).json()).find(
    (value: { code: string }) => value.code === "PRJ-001",
  );
  const supplier = await (
    await page.request.post("/api/v1/suppliers", {
      headers,
      data: { name: `مورد تدقيق تجريبي ${randomUUID().slice(0, 8)}` },
    })
  ).json();
  await seedPriceHistory(page, headers, project.id, supplier.id);
  const content = uniquePdf();
  const number = `AUD-${randomUUID().slice(0, 8)}`;
  const upload = await page.request.post("/api/v1/invoices", {
    headers: { ...headers, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      note: "عينة مصطنعة لاختبار التدقيق المالي.",
      file: {
        name: `تدقيق-مالي-تجريبي-${randomUUID().slice(0, 6)}.pdf`,
        mimeType: "application/pdf",
        buffer: content,
      },
    },
  });
  expect(upload.status()).toBe(201);
  const invoice = await upload.json();

  await page.goto(`/invoices/${invoice.id}/edit`);
  await page.getByLabel("المورد", { exact: true }).selectOption(supplier.id);
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill(number);
  await page.getByLabel("تاريخ الفاتورة", { exact: true }).fill("2026-09-11");
  await page.getByLabel("العملة", { exact: true }).selectOption("SAR");
  await page.getByRole("button", { name: "إضافة بند", exact: true }).click();
  const line = page.getByRole("group", { name: "البند 1", exact: true });
  await line.getByLabel("وصف البند", { exact: true }).fill("مواد تدقيق تجريبية");
  await line.getByLabel("الكمية", { exact: true }).fill("2");
  await line.getByLabel("سعر الوحدة", { exact: true }).fill("100");
  await line.getByLabel("خصم البند", { exact: true }).fill("10");
  await line.getByLabel("نسبة الضريبة %", { exact: true }).fill("15");
  await page.getByLabel("الصافي قبل الضريبة", { exact: false }).fill("190.00");
  await page.getByLabel("إجمالي الضريبة", { exact: false }).fill("28.50");
  await page.getByLabel("الإجمالي المستحق", { exact: false }).fill("218.50");
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true }).click();
  await expect(page.getByRole("heading", { name: "توجد نتائج تحتاج مراجعة" })).toBeVisible();
  await expect(
    page.locator(".audit-check").filter({ hasText: "الصافي قبل الضريبة" }),
  ).toContainText("مطابق");
  const priceWarning = page.locator(".audit-check").filter({ hasText: "تحليل الأسعار التاريخية" });
  await expect(priceWarning).toContainText("95.0000 SAR");
  await expect(priceWarning).toContainText("45.0000 SAR");
  await expect(priceWarning).toContainText("55.0000 SAR");
  await expect(priceWarning).toContainText("111.1%");

  await page.getByRole("link", { name: "تعديل بيانات الفاتورة" }).click();
  await page.getByLabel("الإجمالي المستحق", { exact: false }).fill("220.00");
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true }).click();
  await expect(page.getByRole("heading", { name: "توجد نتائج تحتاج مراجعة" })).toBeVisible();
  const totalWarning = page.locator(".audit-check").filter({ hasText: "الإجمالي المستحق" });
  await expect(totalWarning).toContainText("220.00 SAR");
  await expect(totalWarning).toContainText("218.50 SAR");

  const secondUpload = await page.request.post("/api/v1/invoices", {
    headers: { ...headers, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      note: "نسخة مصطنعة لاختبار كشف التكرار.",
      file: { name: "نسخة-مطابقة-تجريبية.pdf", mimeType: "application/pdf", buffer: content },
    },
  });
  const second = await secondUpload.json();
  const savedSecond = await page.request.put(`/api/v1/invoices/${second.id}`, {
    headers,
    data: {
      revision: second.revision,
      supplier_id: supplier.id,
      invoice_number: number.toLowerCase().replace("-", " "),
      invoice_date: "2026-09-11",
      currency: "SAR",
      note: second.note,
      document_totals: { subtotal: "190", tax_total: "28.5", grand_total: "218.50" },
      items: [
        {
          description: "مواد تدقيق تجريبية",
          unit: null,
          quantity: "2",
          unit_price: "100",
          discount_amount: "10",
          tax_rate: "15",
        },
      ],
    },
  });
  expect(savedSecond.status()).toBe(200);
  await page.goto(`/invoices/${second.id}`);
  await expect(
    page.locator(".audit-check").filter({ hasText: "تطابق الملف الأصلي" }),
  ).toContainText("يحتاج مراجعة");
  await expect(
    page.locator(".audit-check").filter({ hasText: "تكرار بيانات الفاتورة" }),
  ).toContainText("يحتاج مراجعة");
  const fuzzyDuplicate = page
    .locator(".audit-check")
    .filter({ hasText: "التكرار التقريبي وتشابه المحتوى" });
  await expect(fuzzyDuplicate).toContainText("يحتاج مراجعة");
  await expect(fuzzyDuplicate).toContainText("حد التنبيه 85%");
  await expect(fuzzyDuplicate).toContainText("محتوى البنود");
  fs.mkdirSync(qa, { recursive: true });
  await page.screenshot({ path: path.join(qa, "financial-audit-findings.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".audit-check")).toHaveCount(18);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(qa, "financial-audit-mobile.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
