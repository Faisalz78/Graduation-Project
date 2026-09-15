import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const sample = fs.readFileSync(path.join(root, ".local/samples/demo-invoice.pdf"));
const qa = path.join(root, ".local/qa");
fs.mkdirSync(qa, { recursive: true });

test("a 10 MiB PDF survives the web proxy without truncation", async ({ page }) => {
  const targetSize = 10 * 1024 * 1024;
  const marker = sample.lastIndexOf(Buffer.from("startxref"));
  expect(marker).toBeGreaterThan(0);
  // A PDF comment before startxref preserves the original object offsets.
  const padding = Buffer.alloc(targetSize - sample.length, "a");
  padding[0] = 37;
  padding[padding.length - 1] = 10;
  const largePdf = Buffer.concat([sample.subarray(0, marker), padding, sample.subarray(marker)]);
  await login(page);
  await page.goto("/invoices/new");
  await page.locator('input[type="file"]').setInputFiles({
    name: "حد-حجم-الملف-تجريبي.pdf",
    mimeType: "application/pdf",
    buffer: largePdf,
  });
  await page
    .getByLabel("المشروع", { exact: false })
    .selectOption({ label: "تطوير المقر الرئيسي — PRJ-001" });
  await page.getByRole("button", { name: "حفظ المسودة" }).click();
  await expect(page.getByRole("heading", { name: "حد-حجم-الملف-تجريبي.pdf" })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "تحميل الملف الأصلي" }).click();
  const download = await downloadPromise;
  expect(fs.readFileSync((await download.path())!)).toEqual(largePdf);
});

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
  await expect(page.getByText("جارٍ تحميل الفواتير…", { exact: true })).toHaveCount(0);
}

test("desktop login, upload, refresh, download and private draft", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/login");
  await page.screenshot({
    path: path.join(qa, "login-desktop.png"),
    fullPage: true,
    caret: "initial",
  });
  await login(page);
  await page.screenshot({
    path: path.join(qa, "invoices-desktop.png"),
    fullPage: true,
    caret: "initial",
  });
  await page.getByRole("link", { name: "رفع فاتورة", exact: true }).click();
  await page
    .locator('input[type="file"]')
    .setInputFiles({ name: "فاتورة-تجريبية.pdf", mimeType: "application/pdf", buffer: sample });
  await page
    .getByLabel("المشروع", { exact: false })
    .selectOption({ label: "تطوير المقر الرئيسي — PRJ-001" });
  await page
    .getByLabel("ملاحظة", { exact: false })
    .fill("بيانات تجريبية للتحقق من الرفع والحفظ، وليست فاتورة مستحقة للدفع.");
  await page.screenshot({
    path: path.join(qa, "upload-desktop.png"),
    fullPage: true,
    caret: "initial",
  });
  await page.getByRole("button", { name: "حفظ المسودة" }).click();
  await expect(page).toHaveURL(/\/invoices\/[a-f0-9-]+\?saved=1/);
  await expect(page.getByRole("heading", { name: "فاتورة-تجريبية.pdf" })).toBeVisible();
  const detailUrl = page.url();
  await page.reload();
  await expect(page.getByText("إنشاء المسودة", { exact: true })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "تحميل الملف الأصلي" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("فاتورة-تجريبية.pdf");
  const downloadedPath = await download.path();
  expect(fs.readFileSync(downloadedPath!)).toEqual(sample);
  await page.screenshot({
    path: path.join(qa, "details-desktop.png"),
    fullPage: true,
    caret: "initial",
  });
  await page.getByRole("button", { name: "تسجيل الخروج" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "employee2@demo.test");
  await page.goto(detailUrl);
  await expect(
    page.getByRole("alert").filter({ hasText: "غير موجودة أو غير متاحة" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("mobile upload, navigation and responsive layout", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: path.join(qa, "invoices-mobile.png"),
    fullPage: true,
    caret: "initial",
  });
  await page.getByRole("link", { name: "المشاريع", exact: true }).click();
  await expect(page.getByRole("heading", { name: "تطوير المقر الرئيسي" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole("link", { name: "فواتيري", exact: true }).click();
  await page.getByRole("link", { name: "رفع فاتورة", exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "فاتورة-الجوال-تجريبية.pdf",
    mimeType: "application/pdf",
    buffer: sample,
  });
  await page
    .getByLabel("المشروع", { exact: false })
    .selectOption({ label: "تجهيز مستودع العمليات — PRJ-002" });
  await page.screenshot({
    path: path.join(qa, "upload-mobile.png"),
    fullPage: true,
    caret: "initial",
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole("button", { name: "حفظ المسودة" }).click();
  await expect(page.getByRole("heading", { name: "فاتورة-الجوال-تجريبية.pdf" })).toBeVisible();
  await page.screenshot({
    path: path.join(qa, "details-mobile.png"),
    fullPage: true,
    caret: "initial",
  });
});

test("wrong credentials, invalid file and reviewer scope", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill("employee@demo.test");
  await page.getByLabel("كلمة المرور", { exact: true }).fill("incorrect");
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "غير صحيحة" })).toBeVisible();
  await login(page);
  await page.getByRole("link", { name: "رفع فاتورة", exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "program.exe",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("invalid"),
  });
  await expect(page.getByRole("alert").filter({ hasText: "اختر ملف PDF" })).toBeVisible();
  await expect(page.getByRole("button", { name: "حفظ المسودة" })).toBeDisabled();
  await page.getByRole("button", { name: "تسجيل الخروج" }).click();
  await login(page, "manager@demo.test");
  await expect(page.getByLabel("تصفية بالحالة")).toHaveValue("PROJECT_REVIEW");
  await expect(page.getByRole("link", { name: "رفع فاتورة", exact: true })).toHaveCount(0);
  await page.goto("/invoices/new");
  await expect(page.getByRole("heading", { name: "رفع الفواتير متاح للموظف" })).toBeVisible();
});
