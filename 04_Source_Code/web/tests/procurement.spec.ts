import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const sample = fs.readFileSync(path.join(root, ".local/samples/demo-invoice.pdf"));
const qa = path.join(root, ".local/qa");

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور", { exact: true }).fill(state.demo_password);
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
}

async function sessionHeaders(page: Page) {
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  return { Origin: "http://127.0.0.1:3000", "X-CSRF-Token": session.csrf_token };
}

function uniquePdf() {
  const marker = sample.lastIndexOf(Buffer.from("startxref"));
  return Buffer.concat([
    sample.subarray(0, marker),
    Buffer.from(`% procurement-test ${randomUUID()}\n`),
    sample.subarray(marker),
  ]);
}

test("purchase order, receipt evidence and invoice matching work end to end", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const suffix = randomUUID().slice(0, 8);
  const orderNumber = `PO-E2E-${suffix}`;
  const receiptNumber = `GR-E2E-${suffix}`;
  const supplierName = `مورد أمر شراء ${suffix}`;

  await login(page, "finance@demo.test");
  const financeHeaders = await sessionHeaders(page);
  const project = (await (await page.request.get("/api/v1/projects")).json()).find(
    (value: { code: string }) => value.code === "PRJ-001",
  );
  const supplierResponse = await page.request.post("/api/v1/suppliers", {
    headers: financeHeaders,
    data: { name: supplierName, tax_number: `TAX-${suffix}` },
  });
  expect(supplierResponse.status()).toBe(201);
  const supplier = await supplierResponse.json();

  await page.getByRole("link", { name: "أوامر الشراء", exact: true }).click();
  await page.getByRole("button", { name: "أمر شراء جديد", exact: true }).click();
  await page.getByLabel("رقم أمر الشراء", { exact: true }).fill(orderNumber);
  await page.getByLabel("المشروع", { exact: true }).selectOption(project.id);
  await page.getByLabel("المورد", { exact: true }).selectOption(supplier.id);
  const orderLine = page.getByRole("group", { name: "البند 1", exact: true });
  await orderLine.getByLabel("وصف البند", { exact: true }).fill("أجهزة شبكة للمشروع");
  await orderLine.getByLabel("الوحدة", { exact: true }).fill("قطعة");
  await orderLine.getByLabel("الكمية المطلوبة", { exact: true }).fill("10");
  await orderLine.getByLabel("سعر الوحدة", { exact: true }).fill("250");
  await orderLine.getByLabel("نسبة الضريبة %", { exact: true }).fill("15");
  await page.getByRole("button", { name: "حفظ أمر الشراء", exact: true }).click();
  await expect(page.getByText("تم إنشاء أمر الشراء وتسجيله في السجل.")).toBeVisible();
  const orderCard = page.locator(".purchase-order-card").filter({ hasText: orderNumber });
  await expect(orderCard).toContainText("لم يُستلم");
  await expect(orderCard.getByRole("button", { name: "تسجيل استلام" })).toHaveCount(0);

  await page.getByRole("button", { name: "تسجيل الخروج" }).click();
  await login(page, "employee@demo.test");
  await page.getByRole("link", { name: "أوامر الشراء", exact: true }).click();
  const employeeCard = page.locator(".purchase-order-card").filter({ hasText: orderNumber });
  await employeeCard.getByRole("button", { name: "تسجيل استلام", exact: true }).click();
  await employeeCard.getByLabel("رقم محضر الاستلام", { exact: true }).fill(receiptNumber);
  await employeeCard.getByLabel("الكمية المستلمة للبند 1", { exact: true }).fill("4");
  await employeeCard.getByLabel("إثبات الاستلام", { exact: true }).setInputFiles({
    name: "إثبات-استلام.pdf",
    mimeType: "application/pdf",
    buffer: sample,
  });
  await employeeCard.getByRole("button", { name: "حفظ محضر الاستلام", exact: true }).click();
  await expect(page.getByText(`تم حفظ محضر الاستلام لأمر الشراء ${orderNumber}.`)).toBeVisible();
  await expect(page.locator(".purchase-order-card").filter({ hasText: orderNumber })).toContainText(
    "المستلم 4.0000 من 10.0000",
  );
  fs.mkdirSync(qa, { recursive: true });
  await page.screenshot({
    path: path.join(qa, "purchase-orders.png"),
    fullPage: true,
    caret: "initial",
  });

  const employeeHeaders = await sessionHeaders(page);
  const upload = await page.request.post("/api/v1/invoices", {
    headers: { ...employeeHeaders, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      note: "فاتورة لاختبار المطابقة الثلاثية.",
      file: {
        name: `فاتورة-مطابقة-${suffix}.pdf`,
        mimeType: "application/pdf",
        buffer: uniquePdf(),
      },
    },
  });
  expect(upload.status()).toBe(201);
  const invoice = await upload.json();
  await page.goto(`/invoices/${invoice.id}/edit`);
  await page.getByLabel("المورد", { exact: true }).selectOption(supplier.id);
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill(`INV-${suffix}`);
  await page.getByLabel("تاريخ الفاتورة", { exact: true }).fill("2026-09-12");
  await page.getByLabel("العملة", { exact: true }).selectOption("SAR");
  await page.getByLabel(/^أمر الشراء/).selectOption({ label: `${orderNumber} — ${supplierName}` });
  await page.getByRole("button", { name: "إضافة بند", exact: true }).click();
  const invoiceLine = page.getByRole("group", { name: "البند 1", exact: true });
  await invoiceLine.getByLabel("وصف البند", { exact: true }).fill("أجهزة شبكة للمشروع");
  await invoiceLine.getByLabel(/^الوحدة/).fill("قطعة");
  await invoiceLine.getByLabel("الكمية", { exact: true }).fill("4");
  await invoiceLine.getByLabel("سعر الوحدة", { exact: true }).fill("250");
  await invoiceLine.getByLabel("خصم البند", { exact: true }).fill("0");
  await invoiceLine.getByLabel("نسبة الضريبة %", { exact: true }).fill("15");
  await invoiceLine.getByLabel(/^بند أمر الشراء/).selectOption({ index: 1 });
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true }).click();

  for (const label of ["بيانات أمر الشراء", "مطابقة بنود أمر الشراء", "مطابقة الاستلام"]) {
    await expect(page.locator(".audit-check").filter({ hasText: label })).toContainText("مطابق");
  }
  await expect(
    page.locator(".invoice-financial").getByText("مرتبط بالبند 1 من أمر الشراء"),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(qa, "purchase-order-matching.png"),
    fullPage: true,
    caret: "initial",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(qa, "purchase-order-matching-mobile.png"),
    fullPage: true,
    caret: "initial",
  });
  expect(errors).toEqual([]);
});
