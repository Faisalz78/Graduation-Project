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

test("finance configures a BOQ budget and an employee classifies an invoice line", async ({
  page,
}) => {
  const suffix = randomUUID().replaceAll("-", "").slice(0, 7).toUpperCase();
  const code = `B${suffix}`;
  await login(page, "finance@demo.test");
  const projects = await (await page.request.get("/api/v1/projects")).json();
  const project = projects.find((value: { code: string }) => value.code === "PRJ-001");

  await page.getByRole("link", { name: "ميزانيات المشاريع", exact: true }).click();
  await page.getByLabel("المشروع", { exact: true }).selectOption(project.id);
  await page.getByLabel("العملة", { exact: true }).selectOption("SAR");
  await page.getByLabel("رمز فئة المصروف").fill(code);
  await page.getByLabel("اسم فئة المصروف").fill(`فئة اختبار ${suffix}`);
  await page.getByRole("button", { name: "إضافة فئة", exact: true }).click();
  await expect(page.getByText("أُضيفت فئة المصروف وسُجلت في سجل التدقيق.")).toBeVisible();

  await page.getByLabel("إجمالي الميزانية (SAR)").fill("999999999999999.99");
  await page.getByRole("button", { name: "إضافة بند", exact: true }).click();
  const budgetLine = page.locator(".budget-line").last();
  const categoryId = await budgetLine
    .locator("option")
    .filter({ hasText: code })
    .getAttribute("value");
  await budgetLine.getByLabel("فئة المصروف").selectOption(categoryId!);
  await budgetLine.getByLabel("وصف بند الميزانية").fill(`توريد تجريبي ${suffix}`);
  await budgetLine.getByLabel("المخصص").fill("1000.00");
  await page.getByRole("button", { name: "حفظ الميزانية", exact: true }).click();
  await expect(
    page.getByText("حُفظت الميزانية وحُدثت أرقام الاستخدام وسجل التدقيق."),
  ).toBeVisible();
  await expect(budgetLine).toContainText("متبقي");
  fs.mkdirSync(qa, { recursive: true });
  await page.screenshot({ path: path.join(qa, "project-budget.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(qa, "project-budget-narrow.png"), fullPage: true });
  await page.setViewportSize({ width: 1365, height: 900 });

  await login(page, "manager@demo.test");
  await page.getByRole("link", { name: "ميزانيات المشاريع", exact: true }).click();
  await page.getByLabel("المشروع", { exact: true }).selectOption(project.id);
  await expect(page.getByLabel("وصف بند الميزانية").last()).toHaveValue(`توريد تجريبي ${suffix}`);
  await expect(page.getByRole("button", { name: "حفظ الميزانية", exact: true })).toHaveCount(0);

  await login(page, "employee@demo.test");
  const upload = await page.request.post("/api/v1/invoices", {
    headers: { ...(await headers(page)), "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      file: { name: `budget-${suffix}.pdf`, mimeType: "application/pdf", buffer: sample },
    },
  });
  expect(upload.status()).toBe(201);
  const invoice = await upload.json();
  await page.goto(`/invoices/${invoice.id}/edit`);
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill(`BUDGET-${suffix}`);
  await page.getByLabel("تاريخ الفاتورة", { exact: true }).fill("2026-09-12");
  await page.getByLabel("العملة", { exact: true }).selectOption("SAR");
  await page.getByRole("button", { name: "إضافة بند", exact: true }).click();
  const invoiceLine = page.getByRole("group", { name: "البند 1", exact: true });
  await invoiceLine.getByLabel("وصف البند", { exact: true }).fill("مواد مصنفة على الميزانية");
  await invoiceLine.getByLabel("الكمية", { exact: true }).fill("1");
  await invoiceLine.getByLabel("سعر الوحدة", { exact: true }).fill("100");
  await invoiceLine.getByLabel("خصم البند", { exact: true }).fill("0");
  await invoiceLine.getByLabel("نسبة الضريبة %", { exact: true }).fill("15");
  const budgetLineId = await invoiceLine
    .locator("option")
    .filter({ hasText: code })
    .getAttribute("value");
  await invoiceLine.getByLabel(/^بند ميزانية المشروع/).selectOption(budgetLineId!);
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true }).click();
  await expect(page.getByText("جميع بنود الفاتورة مصنفة على بنود ميزانية المشروع.")).toBeVisible();
  await expect(
    page.getByText("الأثر المتوقع للمستند ضمن إجمالي ميزانية المشروع المسجلة."),
  ).toBeVisible();
  await page.screenshot({ path: path.join(qa, "invoice-budget-allocation.png"), fullPage: true });
});
