import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const sample = fs.readFileSync(path.join(root, ".local/samples/demo-invoice.pdf"));

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور", { exact: true }).fill(state.demo_password);
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
}

function uniquePdf() {
  const marker = sample.lastIndexOf(Buffer.from("startxref"));
  return Buffer.concat([
    sample.subarray(0, marker),
    Buffer.from("% report-notification-test " + randomUUID() + "\n"),
    sample.subarray(marker),
  ]);
}

test("workflow alert appears in the assigned manager inbox and can be read", async ({ page }) => {
  await login(page, "employee@demo.test");
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const headers = { Origin: "http://127.0.0.1:3000", "X-CSRF-Token": session.csrf_token };
  const project = (await (await page.request.get("/api/v1/projects")).json()).find(
    (value: { code: string }) => value.code === "PRJ-001",
  );
  const supplier = await (
    await page.request.post("/api/v1/suppliers", {
      headers,
      data: {
        name: "مورد تنبيه " + randomUUID().slice(0, 8),
        region_code: "RIYADH",
      },
    })
  ).json();
  const upload = await page.request.post("/api/v1/invoices", {
    headers: { ...headers, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      note: "فاتورة مصطنعة لاختبار تنبيه المراجع.",
      file: {
        name: "تنبيه-مراجعة.pdf",
        mimeType: "application/pdf",
        buffer: uniquePdf(),
      },
    },
  });
  expect(upload.status()).toBe(201);
  const draft = await upload.json();
  const number = "ALERT-" + randomUUID().slice(0, 8);
  const saved = await page.request.put("/api/v1/invoices/" + draft.id, {
    headers,
    data: {
      revision: draft.revision,
      supplier_id: supplier.id,
      invoice_number: number,
      invoice_date: "2026-09-13",
      currency: "SAR",
      note: draft.note,
      document_totals: null,
      items: [
        {
          description: "مواد اختبار التنبيه",
          unit: "قطعة",
          quantity: "1",
          unit_price: "100",
          discount_amount: "0",
          tax_rate: "15",
        },
      ],
    },
  });
  const ready = await saved.json();
  const submitted = await page.request.post("/api/v1/invoices/" + ready.id + "/workflow", {
    headers,
    data: { revision: ready.revision, action: "SUBMIT", confirmed: true },
  });
  expect(submitted.status()).toBe(200);

  await page.getByRole("button", { name: "تسجيل الخروج" }).click();
  await login(page, "manager@demo.test");
  await page.getByRole("link", { name: /التنبيهات/ }).click();
  const row = page.locator(".notification-row").filter({ hasText: number });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "تمييز كمقروء" }).click();
  await expect(row.getByRole("button", { name: "تمييز كمقروء" })).toHaveCount(0);
});

test("manager downloads the three scoped CSV reports from the reports page", async ({ page }) => {
  await login(page, "manager@demo.test");
  await page.getByRole("link", { name: "التقارير", exact: true }).click();
  await expect(page.getByRole("heading", { name: "التقارير والتصدير" })).toBeVisible();
  const projectId = await page
    .getByLabel("المشروع")
    .locator("option")
    .filter({ hasText: "PRJ-001" })
    .getAttribute("value");
  await page.getByLabel("المشروع").selectOption(projectId!);
  await page.getByLabel("العملة").selectOption("SAR");
  await page.getByLabel("حالة المستند").selectOption("PROJECT_REVIEW");

  const invoiceDownload = page.waitForEvent("download");
  await page
    .locator(".report-card")
    .filter({ hasText: "سجل الفواتير" })
    .getByRole("link", { name: "تنزيل CSV" })
    .click();
  const invoiceFile = await invoiceDownload;
  expect(invoiceFile.suggestedFilename()).toMatch(/^invoice-register-\d{4}-\d{2}-\d{2}\.csv$/);
  const bytes = fs.readFileSync((await invoiceFile.path())!);
  expect(bytes.subarray(0, 3)).toEqual(Buffer.from([0xef, 0xbb, 0xbf]));
  expect(bytes.toString("utf8")).toContain("رقم المستند");

  const regionalDownload = page.waitForEvent("download");
  await page
    .locator(".report-card")
    .filter({ hasText: "المقارنة الإقليمية" })
    .getByRole("link", { name: "تنزيل CSV" })
    .click();
  expect((await regionalDownload).suggestedFilename()).toMatch(/^regional-prices-/);

  const budgetDownload = page.waitForEvent("download");
  await page
    .locator(".report-card")
    .filter({ hasText: "ملخص ميزانيات المشاريع" })
    .getByRole("link", { name: "تنزيل CSV" })
    .click();
  expect((await budgetDownload).suggestedFilename()).toMatch(/^project-budgets-/);
});
