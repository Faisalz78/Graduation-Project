import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const qa = path.join(root, ".local/qa");

async function login(page: Page, email: string, password = state.demo_password) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور", { exact: true }).fill(password);
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
}

test("finance creates an account and project, assigns access, and resets credentials", async ({
  page,
}) => {
  const suffix = randomUUID().replaceAll("-", "").slice(0, 7).toUpperCase();
  const userName = `موظف إدارة ${suffix}`;
  const email = `admin-${suffix.toLowerCase()}@example.test`;
  const initialPassword = `Initial-${suffix}-Aa1!`;
  const resetPassword = `Reset-${suffix}-Bb2!`;
  const projectName = `مشروع إدارة ${suffix}`;
  const projectCode = `ADM-${suffix}`;

  await login(page, "finance@demo.test");
  await page.getByRole("link", { name: "إدارة النظام", exact: true }).click();
  await expect(page.getByRole("heading", { name: "المشاريع والمستخدمون" })).toBeVisible();

  const userForm = page.locator(".administration-create").first();
  await userForm.getByLabel("اسم المستخدم").fill(userName);
  await userForm.getByLabel("البريد الإلكتروني", { exact: true }).fill(email);
  await userForm.getByLabel("الدور", { exact: true }).selectOption("EMPLOYEE");
  await userForm.getByLabel("كلمة المرور المؤقتة", { exact: true }).fill(initialPassword);
  await userForm.getByRole("button", { name: "إنشاء الحساب", exact: true }).click();
  await expect(page.getByText("أُنشئ الحساب وسُجلت العملية.", { exact: false })).toBeVisible();

  const userCard = page.locator(`[data-user-email="${email}"]`);
  await expect(userCard.getByLabel("الاسم", { exact: true })).toHaveValue(userName);
  await expect(userCard).toContainText("نشط");

  const projectForm = page.locator(".project-create");
  await projectForm.getByLabel("اسم المشروع", { exact: true }).fill(projectName);
  await projectForm.getByLabel("رمز المشروع", { exact: true }).fill(projectCode);
  await projectForm.getByRole("button", { name: "إنشاء المشروع", exact: true }).click();
  await expect(page.getByText("أُنشئ المشروع وسُجلت العملية.", { exact: false })).toBeVisible();

  const projectCard = page.locator(`[data-project-code="${projectCode}"]`);
  await projectCard.getByRole("checkbox", { name: new RegExp(userName) }).check();
  await projectCard.getByRole("checkbox", { name: /^مدير المشروع / }).check();
  await projectCard.getByRole("button", { name: "حفظ الأعضاء", exact: true }).click();
  await expect(page.getByText("حُفظ أعضاء المشروع وطُبقت صلاحياتهم فورًا.")).toBeVisible();

  await userCard.getByLabel("كلمة مرور مؤقتة جديدة").fill(resetPassword);
  await userCard.getByRole("button", { name: "إعادة الضبط", exact: true }).click();
  await expect(
    page.getByText("أُعيد ضبط كلمة المرور وأُغلقت جلسات المستخدم السابقة."),
  ).toBeVisible();

  fs.mkdirSync(qa, { recursive: true });
  await page.screenshot({ path: path.join(qa, "project-user-administration.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(qa, "project-user-administration-narrow.png"),
    fullPage: true,
  });

  await login(page, email, resetPassword);
  await expect(page.getByRole("link", { name: "إدارة النظام", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "المشاريع", exact: true }).click();
  await expect(page.getByText(projectName, { exact: true })).toBeVisible();
});
