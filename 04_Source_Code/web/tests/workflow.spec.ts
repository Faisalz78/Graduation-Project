import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const sample = fs.readFileSync(path.join(root, ".local/samples/demo-invoice.pdf"));
const qa = path.join(root, ".local/qa");
const cookies = new Map<string, Awaited<ReturnType<BrowserContext["cookies"]>>>();

async function login(page: Page, role = "employee") {
  if (cookies.has(role)) {
    await page.context().clearCookies();
    await page.context().addCookies(cookies.get(role)!);
    await page.goto("/invoices");
  } else {
    await page.goto("/login");
    await page.getByLabel("البريد الإلكتروني").fill(`${role}@demo.test`);
    await page.getByLabel("كلمة المرور", { exact: true }).fill(state.demo_password);
    await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
    await expect(page).toHaveURL(/\/invoices$/);
    cookies.set(role, await page.context().cookies());
  }
  await expect(
    page.getByRole("heading", {
      name: role === "employee" ? "فواتيرك، بوضوح." : "مراجعة الفواتير",
      exact: true,
    }),
  ).toBeVisible();
}

async function fixture(page: Page, complete = true) {
  await login(page);
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const headers = { Origin: "http://127.0.0.1:3000", "X-CSRF-Token": session.csrf_token };
  const projects = await (await page.request.get("/api/v1/projects")).json();
  const project = projects.find((value: { code: string }) => value.code === "PRJ-001");
  const name = `فاتورة-مسار-تجريبية-${randomUUID().slice(0, 8)}.pdf`;
  const response = await page.request.post("/api/v1/invoices", {
    headers: { ...headers, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      note: "عينة لاختبار دورة المراجعة، ليست مطالبة مالية حقيقية.",
      file: { name, mimeType: "application/pdf", buffer: sample },
    },
  });
  expect(response.status()).toBe(201);
  let invoice = await response.json();
  if (complete) {
    const supplier = await (
      await page.request.post("/api/v1/suppliers", {
        headers,
        data: { name: `مورد مسار تجريبي ${randomUUID().slice(0, 8)}` },
      })
    ).json();
    const saved = await page.request.put(`/api/v1/invoices/${invoice.id}`, {
      headers,
      data: {
        revision: invoice.revision,
        supplier_id: supplier.id,
        invoice_number: "TEST-WORKFLOW",
        invoice_date: "2026-09-10",
        currency: "SAR",
        note: invoice.note,
        items: [
          {
            description: "مواد تجريبية",
            unit: "قطعة",
            quantity: "2",
            unit_price: "100",
            discount_amount: "10",
            tax_rate: "15",
          },
        ],
      },
    });
    expect(saved.status()).toBe(200);
    invoice = await saved.json();
  }
  await page.goto(`/invoices/${invoice.id}`);
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  return invoice as { id: string; revision: number; attachment: { name: string } };
}

async function submit(page: Page, again = false) {
  await page
    .getByRole("button", { name: again ? "إعادة الإرسال للمراجعة" : "إرسال للمراجعة", exact: true })
    .click();
  await expect(page.getByRole("button", { name: "تأكيد الإرسال", exact: true })).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "راجعت بيانات الفاتورة والبنود وطابقتها مع الملف الأصلي." })
    .check();
  await page.getByRole("button", { name: "تأكيد الإرسال", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "مراجعة مدير المشروع", exact: true }),
  ).toBeVisible();
}

async function approve(page: Page, finance = false) {
  await page
    .getByRole("button", {
      name: finance ? "اعتماد الفاتورة" : "موافقة وإرسال للمالية",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "تأكيد الموافقة", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: finance ? "معتمدة" : "مراجعة المالية", exact: true }),
  ).toBeVisible();
}

test("employee submits, project approves and finance approves with original and history", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const invoice = await fixture(page);
  await submit(page);
  await expect(page.getByRole("link", { name: "تعديل بيانات الفاتورة" })).toHaveCount(0);
  await login(page, "manager");
  await expect(page.getByLabel("تصفية بالحالة")).toHaveValue("PROJECT_REVIEW");
  await page.getByRole("link", { name: `فتح ${invoice.attachment.name}`, exact: true }).click();
  await expect(page.getByRole("button", { name: "موافقة وإرسال للمالية" })).toBeVisible();
  await page.screenshot({ path: path.join(qa, "workflow-project-review.png"), fullPage: true });
  await approve(page);
  await login(page, "finance");
  await expect(page.getByLabel("تصفية بالحالة")).toHaveValue("FINANCE_REVIEW");
  await page.getByRole("link", { name: `فتح ${invoice.attachment.name}`, exact: true }).click();
  await approve(page, true);
  await page.reload();
  await expect(page.getByText("اعتماد المالية", { exact: true }).last()).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "تحميل الملف الأصلي" }).click();
  expect(fs.readFileSync((await (await download).path())!)).toEqual(sample);
  await page.locator(".audit-change summary").last().click();
  await expect(page.locator(".audit-change").last().getByTestId("grand-total")).toHaveText(
    "218.50 SAR",
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(qa, "workflow-approved.png"), fullPage: true });
  await login(page);
  await page.getByLabel("تصفية بالحالة").selectOption("APPROVED");
  await page.getByRole("link", { name: `فتح ${invoice.attachment.name}`, exact: true }).click();
  await expect(page.getByRole("heading", { name: "معتمدة", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("finance returns for correction, employee resubmits and project can reject on mobile", async ({
  page,
}) => {
  const invoice = await fixture(page);
  await submit(page);
  await login(page, "manager");
  await page.goto(`/invoices/${invoice.id}`);
  await approve(page);
  await login(page, "finance");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/invoices/${invoice.id}`);
  await page.getByRole("button", { name: "طلب تعديل", exact: true }).click();
  await page.getByRole("button", { name: "تأكيد طلب التعديل" }).click();
  expect((await (await page.request.get(`/api/v1/invoices/${invoice.id}`)).json()).status).toBe(
    "FINANCE_REVIEW",
  );
  await page
    .getByLabel("السبب والتفاصيل المطلوبة")
    .fill("يرجى تصحيح الكمية إلى 3 حسب الأصل التجريبي.");
  await page.getByRole("button", { name: "تأكيد طلب التعديل" }).click();
  await expect(page.getByRole("heading", { name: "مطلوب تعديل", exact: true })).toBeVisible();
  await login(page);
  await page.goto(`/invoices/${invoice.id}`);
  await expect(page.locator(".review-reason")).toContainText("تصحيح الكمية");
  await page.screenshot({ path: path.join(qa, "workflow-changes-mobile.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("link", { name: "تعديل بيانات الفاتورة" }).click();
  await page
    .getByRole("group", { name: "البند 1", exact: true })
    .getByLabel("الكمية", { exact: true })
    .fill("3");
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة" }).click();
  await submit(page, true);
  await login(page, "manager");
  await page.goto(`/invoices/${invoice.id}`);
  await page.getByRole("button", { name: "رفض الفاتورة", exact: true }).click();
  await page.getByLabel("السبب والتفاصيل المطلوبة").fill("رفض تجريبي للتحقق من تسجيل السبب.");
  await page.getByRole("button", { name: "تأكيد الرفض", exact: true }).click();
  await expect(page.getByRole("heading", { name: "مرفوضة", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await login(page);
  await page.goto(`/invoices/${invoice.id}/edit`);
  await expect(
    page.getByRole("heading", { name: "الفاتورة غير متاحة للتعديل حاليًا" }),
  ).toBeVisible();
});

test("stale reviewer keeps comment and must reload before making a new decision", async ({
  page,
  context,
}) => {
  const invoice = await fixture(page);
  await submit(page);
  await login(page, "manager");
  await page.goto(`/invoices/${invoice.id}`);
  const second = await context.newPage();
  await second.goto(`/invoices/${invoice.id}`);
  await second.getByRole("button", { name: "رفض الفاتورة", exact: true }).click();
  await second.getByLabel("السبب والتفاصيل المطلوبة").fill("تعليق قديم يجب ألا يتحول إلى قرار.");
  await approve(page);
  await second.getByRole("button", { name: "تأكيد الرفض" }).click();
  await expect(second.locator(".workflow-form .error-box")).toContainText("تغيرت نسخة الفاتورة");
  await expect(second.getByLabel("السبب والتفاصيل المطلوبة")).toHaveValue(
    "تعليق قديم يجب ألا يتحول إلى قرار.",
  );
  await second.getByRole("button", { name: "تحميل أحدث نسخة للمراجعة" }).click();
  await expect(second.getByRole("heading", { name: "مراجعة المالية", exact: true })).toBeVisible();
  await expect(second.getByRole("button", { name: "رفض الفاتورة", exact: true })).toHaveCount(0);
  const result = await (await page.request.get(`/api/v1/invoices/${invoice.id}`)).json();
  expect(
    result.events.filter((event: { action: string }) => event.action === "INVOICE_REJECTED"),
  ).toHaveLength(0);
});

test("incomplete draft blocks submission and an editor opened before submission cannot save", async ({
  page,
  context,
}) => {
  await fixture(page, false);
  await expect(page.locator(".submission-missing")).toContainText("المورد");
  await expect(page.getByRole("button", { name: "إرسال للمراجعة", exact: true })).toBeDisabled();
  const invoice = await fixture(page);
  const editor = await context.newPage();
  await editor.goto(`/invoices/${invoice.id}/edit`);
  await editor.getByLabel("رقم الفاتورة", { exact: true }).fill("UNSAVED-AFTER-SUBMIT");
  await submit(page);
  await editor.getByRole("button", { name: "حفظ بيانات الفاتورة" }).click();
  await expect(editor.locator(".editor-main > .error-box")).toContainText("التعديل متاح للمسودة");
  await expect(editor.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue(
    "UNSAVED-AFTER-SUBMIT",
  );
  await editor.getByRole("button", { name: "تحميل النسخة الأحدث وإلغاء تعديلاتي" }).click();
  await expect(
    editor.getByRole("heading", { name: "الفاتورة غير متاحة للتعديل حاليًا" }),
  ).toBeVisible();
});
