import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const root = path.resolve(__dirname, "../../..");
const state = JSON.parse(fs.readFileSync(path.join(root, ".local/runtime.json"), "utf8"));
const qa = path.join(root, ".local/qa");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("البريد الإلكتروني").fill("employee@demo.test");
  await page.getByLabel("كلمة المرور", { exact: true }).fill(state.demo_password);
  await page.getByRole("button", { name: "الدخول إلى مساحة العمل" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
}

function xmlInvoice(invoiceNumber: string, supplierName: string) {
  return Buffer.from(`<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>${invoiceNumber}</cbc:ID>
  <cbc:IssueDate>2026-09-11</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>SAR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>${supplierName}</cbc:Name></cac:PartyName>
    <cac:PartyTaxScheme><cbc:CompanyID>310123456700003</cbc:CompanyID></cac:PartyTaxScheme>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="SAR">28.50</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="SAR">190.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="SAR">218.50</cbc:TaxInclusiveAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="PCE">2</cbc:InvoicedQuantity>
    <cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator><cbc:Amount>10.00</cbc:Amount></cac:AllowanceCharge>
    <cac:Item><cbc:Description>مواد XML تجريبية</cbc:Description>
      <cac:ClassifiedTaxCategory><cbc:Percent>15</cbc:Percent></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount>100.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>`);
}

test("UBL XML is extracted, imported, and compared after confirmation", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const headers = { Origin: "http://127.0.0.1:3000", "X-CSRF-Token": session.csrf_token };
  const project = (await (await page.request.get("/api/v1/projects")).json()).find(
    (value: { code: string }) => value.code === "PRJ-001",
  );
  const supplierName = `مورد XML تجريبي ${randomUUID().slice(0, 8)}`;
  const supplier = await (
    await page.request.post("/api/v1/suppliers", {
      headers,
      data: {
        name: supplierName,
        tax_number: "310123456700003",
      },
    })
  ).json();
  const invoiceNumber = `XML-${randomUUID().slice(0, 8)}`;
  const upload = await page.request.post("/api/v1/invoices", {
    headers: { ...headers, "Idempotency-Key": randomUUID() },
    multipart: {
      project_id: project.id,
      note: "عينة UBL XML مصطنعة لاختبار مقارنة المصادر.",
      file: {
        name: `فاتورة-xml-تجريبية-${randomUUID().slice(0, 6)}.xml`,
        mimeType: "application/xml",
        buffer: xmlInvoice(invoiceNumber, supplierName),
      },
    },
  });
  expect(upload.status()).toBe(201);
  const invoice = await upload.json();

  await page.goto(`/invoices/${invoice.id}/edit`);
  await page.getByRole("button", { name: "استخراج البيانات", exact: true }).click();
  await expect(page.getByRole("heading", { name: "المصادر المنظمة (1)" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("ملف UBL XML", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "نقل الاقتراحات للحقول الفارغة" }).click();
  await expect(page.getByLabel("رقم الفاتورة", { exact: true })).toHaveValue(invoiceNumber);
  await expect(page.getByLabel("وصف البند", { exact: true })).toHaveValue("مواد XML تجريبية");
  await expect(page.getByRole("textbox", { name: "الوحدة اختياري", exact: true })).toHaveValue(
    "PCE",
  );
  await page.getByLabel("المورد", { exact: true }).selectOption(supplier.id);
  await page
    .getByLabel("راجعت الحقول والبنود المقترحة وصححتها وطابقتها مع الفاتورة الأصلية.")
    .check();
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true }).click();
  const xmlCheck = page.locator(".audit-check").filter({ hasText: "مطابقة بيانات XML" });
  await expect(xmlCheck).toContainText("مطابق");

  await page.getByRole("link", { name: "تعديل بيانات الفاتورة" }).click();
  await page.getByLabel("رقم الفاتورة", { exact: true }).fill(`${invoiceNumber}-CHANGED`);
  await page.getByRole("button", { name: "حفظ بيانات الفاتورة", exact: true }).click();
  await expect(xmlCheck).toContainText("يحتاج مراجعة");
  await expect(xmlCheck).toContainText("مختلف");
  await expect(xmlCheck).toContainText(invoiceNumber);
  fs.mkdirSync(qa, { recursive: true });
  await page.screenshot({ path: path.join(qa, "structured-source-mismatch.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".audit-check")).toHaveCount(18);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: path.join(qa, "structured-source-mobile.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
