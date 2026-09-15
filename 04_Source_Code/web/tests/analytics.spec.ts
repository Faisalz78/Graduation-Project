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

test("manager dashboard traces an exception to its explainable risk", async ({ page }) => {
  const suffix = randomUUID().slice(0, 8);
  const number = `DASH-RISK-${suffix}`;
  await login(page, "employee@demo.test");
  const employeeHeaders = await headers(page);
  const project = (await (await page.request.get("/api/v1/projects")).json()).find(
    (value: { code: string }) => value.code === "PRJ-001",
  );
  const supplier = await (
    await page.request.post("/api/v1/suppliers", {
      headers: employeeHeaders,
      data: { name: `مورد لوحة ${suffix}`, tax_number: `VAT-DASH-${suffix}` },
    })
  ).json();
  const upload = await page.request.post("/api/v1/invoices", {
    headers: { ...employeeHeaders, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      file: { name: `dashboard-${suffix}.pdf`, mimeType: "application/pdf", buffer: sample },
    },
  });
  let invoice = await upload.json();
  invoice = await (
    await page.request.put(`/api/v1/invoices/${invoice.id}`, {
      headers: employeeHeaders,
      data: {
        revision: invoice.revision,
        supplier_id: supplier.id,
        invoice_number: number,
        invoice_date: "2026-09-12",
        currency: "SAR",
        document_totals: { subtotal: "999.00", tax_total: "999.00", grand_total: "999.00" },
        note: "عينة مصطنعة لاختبار لوحة المخاطر",
        items: [
          {
            description: "خدمة لوحة مصطنعة",
            unit: "خدمة",
            quantity: "1",
            unit_price: "100",
            discount_amount: "0",
            tax_rate: "15",
          },
        ],
      },
    })
  ).json();
  const submit = await page.request.post(`/api/v1/invoices/${invoice.id}/workflow`, {
    headers: employeeHeaders,
    data: { revision: invoice.revision, action: "SUBMIT", confirmed: true },
  });
  expect(submit.status()).toBe(200);

  await login(page, "manager@demo.test");
  await page.getByRole("link", { name: "اللوحة المالية", exact: true }).click();
  await expect(page.getByRole("heading", { name: "لوحة المصروفات والاستثناءات" })).toBeVisible();
  await expect(page.getByText(number, { exact: true })).toBeVisible();
  await expect(page.getByText("صافي قيد المراجعة", { exact: true })).toBeVisible();
  fs.mkdirSync(qa, { recursive: true });
  await page.screenshot({ path: path.join(qa, "financial-dashboard.png"), fullPage: true });

  await page.getByText(number, { exact: true }).click();
  await expect(page.getByText(/أولوية المراجعة/).first()).toBeVisible();
  await expect(page.getByText("تطابق الملف الأصلي", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: path.join(qa, "explainable-risk.png"), fullPage: true });

  await page.getByRole("link", { name: "اللوحة المالية", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "لوحة المصروفات والاستثناءات" })).toBeVisible();
  await expect(page.getByText(number, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(qa, "financial-dashboard-mobile.png"), fullPage: true });

  await login(page, "employee@demo.test");
  await page.goto("/dashboard");
  await expect(page.getByText("اللوحة المالية مخصصة للمراجعين", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "اللوحة المالية", exact: true })).toHaveCount(0);
});
