import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const sample = fs.readFileSync(path.join(root, ".local/samples/demo-invoice.pdf"));
const qa = path.join(root, ".local/qa");

async function login(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور", { exact: true }).fill(state.demo_password);
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
}

async function headers(page: Page) {
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  return { Origin: "http://127.0.0.1:3000", "X-CSRF-Token": session.csrf_token };
}

async function transition(page: Page, invoice: { id: string; revision: number }, action: string) {
  const response = await page.request.post(`/api/v1/invoices/${invoice.id}/workflow`, {
    headers: await headers(page),
    data: { revision: invoice.revision, action, confirmed: true },
  });
  expect(response.status()).toBe(200);
  return response.json();
}

test("finance configures approval limits and verifies a supplier", async ({ page }) => {
  const suffix = randomUUID().slice(0, 8);
  await login(page, "finance@demo.test");
  const financeHeaders = await headers(page);
  const supplierResponse = await page.request.post("/api/v1/suppliers", {
    headers: financeHeaders,
    data: { name: `مورد تحقق ${suffix}`, tax_number: `VAT-${suffix}` },
  });
  expect(supplierResponse.status()).toBe(201);

  await page.getByRole("link", { name: "حدود الموافقات", exact: true }).click();
  const managerCard = page.locator(".approval-limit-card").filter({ hasText: "manager@demo.test" });
  await managerCard.getByLabel("الحد بعملة SAR").fill("100000.00");
  await managerCard.getByRole("button", { name: /حفظ حد SAR/ }).click();
  await expect(page.getByText("حُفظ حد SAR وسُجل التغيير في سجل التدقيق.")).toBeVisible();
  fs.mkdirSync(qa, { recursive: true });
  await page.screenshot({ path: path.join(qa, "approval-limits.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(qa, "approval-limits-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1365, height: 900 });

  await page.getByRole("link", { name: "الموردون", exact: true }).click();
  await page.getByLabel("البحث عن مورد").fill(`مورد تحقق ${suffix}`);
  const supplierRow = page.locator(".supplier-row").filter({ hasText: `مورد تحقق ${suffix}` });
  await supplierRow.getByRole("button", { name: "مراجعة" }).click();
  await page.getByLabel("الحالة").selectOption("VERIFIED");
  await page.getByLabel("دليل المراجعة أو سبب القرار").fill("مراجعة داخلية لبيانات الاختبار");
  await page.getByRole("button", { name: "حفظ المراجعة" }).click();
  await expect(supplierRow).toContainText("متحقق داخليًا");
  await page.screenshot({ path: path.join(qa, "supplier-verification.png"), fullPage: true });
});

test("employee links a credit note to its reviewed original", async ({ page }) => {
  const suffix = randomUUID().slice(0, 8);
  await login(page, "employee@demo.test");
  const employeeHeaders = await headers(page);
  const project = (await (await page.request.get("/api/v1/projects")).json()).find(
    (value: { code: string }) => value.code === "PRJ-001",
  );
  const supplier = await (
    await page.request.post("/api/v1/suppliers", {
      headers: employeeHeaders,
      data: { name: `مورد إشعار ${suffix}`, tax_number: `VAT-NOTE-${suffix}` },
    })
  ).json();
  const originalUpload = await page.request.post("/api/v1/invoices", {
    headers: { ...employeeHeaders, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      file: { name: `original-${suffix}.pdf`, mimeType: "application/pdf", buffer: sample },
    },
  });
  let original = await originalUpload.json();
  original = await (
    await page.request.put(`/api/v1/invoices/${original.id}`, {
      headers: employeeHeaders,
      data: {
        revision: original.revision,
        supplier_id: supplier.id,
        invoice_number: `ORIGINAL-${suffix}`,
        invoice_date: "2026-09-10",
        currency: "SAR",
        note: "فاتورة أصلية مصطنعة",
        items: [
          {
            description: "خدمة تجريبية",
            unit: "خدمة",
            quantity: "1",
            unit_price: "1000",
            discount_amount: "0",
            tax_rate: "15",
          },
        ],
      },
    })
  ).json();
  original = await transition(page, original, "SUBMIT");
  await login(page, "manager@demo.test");
  original = await transition(page, original, "APPROVE");
  await login(page, "finance@demo.test");
  original = await transition(page, original, "APPROVE");

  await login(page, "employee@demo.test");
  const noteHeaders = await headers(page);
  const noteUpload = await page.request.post("/api/v1/invoices", {
    headers: { ...noteHeaders, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      file: { name: `credit-${suffix}.pdf`, mimeType: "application/pdf", buffer: sample },
    },
  });
  const note = await noteUpload.json();
  await page.goto(`/invoices/${note.id}/edit`);
  await page.getByLabel("نوع المستند").selectOption("CREDIT_NOTE");
  await page.getByLabel("الفاتورة الأصلية").selectOption(original.id);
  await page.getByLabel("المورد", { exact: true }).selectOption(supplier.id);
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill(`CREDIT-${suffix}`);
  await page.getByLabel("تاريخ الفاتورة", { exact: true }).fill("2026-09-12");
  await page.getByLabel("العملة", { exact: true }).selectOption("SAR");
  await page.getByRole("button", { name: "إضافة بند", exact: true }).click();
  const line = page.getByRole("group", { name: "البند 1", exact: true });
  await line.getByLabel("وصف البند", { exact: true }).fill("تسوية خدمة تجريبية");
  await line.getByLabel(/^الوحدة/).fill("خدمة");
  await line.getByLabel("الكمية", { exact: true }).fill("1");
  await line.getByLabel("سعر الوحدة", { exact: true }).fill("100");
  await line.getByLabel("خصم البند", { exact: true }).fill("0");
  await line.getByLabel("نسبة الضريبة %", { exact: true }).fill("15");
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true }).click();
  await expect(
    page.locator(".invoice-financial").getByText("إشعار دائن", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".invoice-financial").getByText(`ORIGINAL-${suffix}`, { exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: path.join(qa, "credit-note-linkage.png"), fullPage: true });
});
