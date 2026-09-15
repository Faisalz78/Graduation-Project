import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const sample = fs.readFileSync(path.join(root, ".local/samples/demo-invoice.pdf"));
const qa = path.join(root, ".local/qa");

async function login(page: Page, email = "employee@demo.test") {
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور", { exact: true }).fill(state.demo_password);
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
  await expect(
    page.getByRole("heading", {
      name: email.startsWith("employee") ? "فواتيرك، بوضوح." : "مراجعة الفواتير",
    }),
  ).toBeVisible();
}

async function newDraft(page: Page) {
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const projects = await (await page.request.get("/api/v1/projects")).json();
  const response = await page.request.post("/api/v1/invoices", {
    headers: {
      Origin: "http://127.0.0.1:3000",
      "X-CSRF-Token": session.csrf_token,
      "Idempotency-Key": randomUUID(),
    },
    multipart: {
      project_id: projects[0].id,
      note: "فاتورة مصطنعة لاختبار إدخال البيانات.",
      file: { name: "فاتورة-بيانات-تجريبية.pdf", mimeType: "application/pdf", buffer: sample },
    },
  });
  expect(response.status()).toBe(201);
  const invoice = await response.json();
  await page.goto(`/invoices/${invoice.id}/edit`);
  await expect(page.getByRole("heading", { name: "بيانات الفاتورة", exact: true })).toBeVisible();
  return invoice.id as string;
}

async function fillItem(
  page: Page,
  position: number,
  data: { description: string; quantity: string; price: string; discount: string; tax: string },
) {
  await page.getByRole("button", { name: "إضافة بند", exact: true }).click();
  const group = page.getByRole("group", { name: `البند ${position}`, exact: true });
  await group.getByLabel("وصف البند", { exact: true }).fill(data.description);
  await group.getByLabel(/^الوحدة/).fill("قطعة");
  await group.getByLabel("الكمية", { exact: true }).fill(data.quantity);
  await group.getByLabel("سعر الوحدة", { exact: true }).fill(data.price);
  await group.getByLabel("خصم البند", { exact: true }).fill(data.discount);
  await group.getByLabel("نسبة الضريبة %", { exact: true }).fill(data.tax);
}

test("manual supplier, exact totals, correction and readable audit history", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  const id = await newDraft(page);
  await page.getByRole("button", { name: "إضافة مورد", exact: true }).click();
  const supplier = `مورد تجريبي ${randomUUID().slice(0, 8)}`;
  await page.getByRole("dialog").getByLabel("اسم المورد", { exact: true }).fill(supplier);
  await page.getByRole("dialog").getByLabel("الرقم الضريبي", { exact: false }).fill("TEST-TAX");
  await page.getByRole("button", { name: "حفظ المورد" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("المورد", { exact: true }).locator("option:checked")).toHaveText(
    supplier,
  );
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill("TEST-DATA-001");
  await page.getByLabel("تاريخ الفاتورة", { exact: true }).fill("2026-09-10");
  await page.getByLabel("العملة", { exact: true }).selectOption("SAR");
  await fillItem(page, 1, {
    description: "بند تجريبي",
    quantity: "2",
    price: "100",
    discount: "10",
    tax: "15",
  });
  await fillItem(page, 2, {
    description: "عينة تقريب عشرية",
    quantity: "3",
    price: "0.335",
    discount: "0",
    tax: "15",
  });
  await expect(page.locator(".calculation-card").getByTestId("grand-total")).toHaveText(
    "219.66 SAR",
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: path.join(qa, "invoice-data-desktop.png"),
    fullPage: true,
    caret: "initial",
  });
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة" }).click();
  await expect(page).toHaveURL(new RegExp(`/invoices/${id}\\?updated=1$`));
  await expect(page.locator(".invoice-financial").getByTestId("grand-total")).toHaveText(
    "219.66 SAR",
  );
  await page.getByRole("link", { name: "تعديل بيانات الفاتورة" }).click();
  await page
    .getByRole("group", { name: "البند 1", exact: true })
    .getByLabel("الكمية", { exact: true })
    .fill("1");
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة" }).click();
  await expect(page.locator(".invoice-financial").getByTestId("grand-total")).toHaveText(
    "104.66 SAR",
  );
  await page.reload();
  await expect(page.getByText("تحديث بيانات الفاتورة — نسخة 3", { exact: true })).toBeVisible();
  await page.locator(".audit-change summary").last().click();
  const history = page.locator(".audit-change").last();
  await expect(history.getByTestId("grand-total").first()).toHaveText("219.66 SAR");
  await expect(history.getByTestId("grand-total").last()).toHaveText("104.66 SAR");
  await page.screenshot({
    path: path.join(qa, "invoice-data-history.png"),
    fullPage: true,
    caret: "initial",
  });
  const file = await page.request.get(`/api/v1/invoices/${id}/file`);
  expect(await file.body()).toEqual(sample);
  expect(errors).toEqual([]);
});

test("mobile validation retains inputs and saves corrected amounts", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  const id = await newDraft(page);
  await page.getByLabel("العملة", { exact: true }).selectOption("SAR");
  await fillItem(page, 1, {
    description: "بند جوال تجريبي",
    quantity: "1",
    price: "7.995",
    discount: "9",
    tax: "0",
  });
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة" }).click();
  await expect(page.locator(".editor-main > .error-box")).toContainText("يتجاوز");
  expect((await (await page.request.get(`/api/v1/invoices/${id}`)).json()).revision).toBe(1);
  const group = page.getByRole("group", { name: "البند 1", exact: true });
  await expect(group.getByLabel("سعر الوحدة", { exact: true })).toHaveValue("7.995");
  await group.getByLabel("خصم البند", { exact: true }).fill("0");
  await expect(page.locator(".calculation-card").getByTestId("grand-total")).toHaveText("8.00 SAR");
  await expect(page.locator(".editor-main > .error-box")).toHaveCount(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(qa, "invoice-data-mobile.png"),
    fullPage: true,
    caret: "initial",
  });
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة" }).click();
  await expect(page.locator(".invoice-financial").getByTestId("grand-total")).toHaveText(
    "8.00 SAR",
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("stale editor cannot overwrite a newer saved revision", async ({ page, context }) => {
  await login(page);
  const id = await newDraft(page);
  const second = await context.newPage();
  await second.goto(`/invoices/${id}/edit`);
  await expect(second.getByRole("heading", { name: "بيانات الفاتورة", exact: true })).toBeVisible();
  await second.getByLabel("رقم الفاتورة", { exact: true }).fill("UNSAVED-SECOND");
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill("SAVED-FIRST");
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة" }).click();
  await expect(page).toHaveURL(new RegExp(`/invoices/${id}\\?updated=1$`));
  await second.getByRole("button", { name: "حفظ بيانات الفاتورة" }).click();
  await expect(second.getByRole("alert").filter({ hasText: "نسخة أحدث" })).toBeVisible();
  await expect(second.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue("UNSAVED-SECOND");
  await second.getByRole("button", { name: "تحميل النسخة الأحدث وإلغاء تعديلاتي" }).click();
  await expect(second.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue("SAVED-FIRST");
  const current = await (await page.request.get(`/api/v1/invoices/${id}`)).json();
  expect(current.revision).toBe(2);
  expect(
    current.events.filter((event: { action: string }) => event.action === "DRAFT_UPDATED"),
  ).toHaveLength(1);
});

test("supplier page is readable to managers and creation is available to finance", async ({
  page,
}) => {
  await login(page, "manager@demo.test");
  await page.getByRole("link", { name: "الموردون", exact: true }).click();
  await expect(page.getByRole("heading", { name: "الموردون", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "إضافة مورد", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "تسجيل الخروج" }).click();
  await login(page, "finance@demo.test");
  await page.getByRole("link", { name: "الموردون", exact: true }).click();
  await page.getByRole("button", { name: "إضافة مورد", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "إغلاق", exact: true }).click();
});
