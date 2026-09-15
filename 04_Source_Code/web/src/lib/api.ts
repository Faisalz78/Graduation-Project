export type User = {
  id: string;
  name: string;
  email: string;
  role: "EMPLOYEE" | "PROJECT_MANAGER" | "FINANCE_MANAGER";
};
export type AuthSession = { user: User; csrf_token: string; expires_at: string };
export type Notification = {
  id: string;
  kind: string;
  title: string;
  message: string;
  invoice_id: string;
  project_id: string;
  created_at: string;
  read_at: string | null;
};
export type NotificationPage = {
  items: Notification[];
  total: number;
  unread_count: number;
  page: number;
  page_size: number;
};
export type Project = { id: string; name: string; code: string };
export type AdminProjectRef = Project & { is_active: boolean };
export type AdminUser = User & {
  is_active: boolean;
  revision: number;
  updated_at: string;
  memberships: {
    project: AdminProjectRef;
    membership_role: "MEMBER" | "MANAGER";
  }[];
};
export type AdminProjectMember = User & {
  is_active: boolean;
  membership_role: "MEMBER" | "MANAGER";
};
export type AdminProject = AdminProjectRef & {
  revision: number;
  updated_at: string;
  members: AdminProjectMember[];
};
export type Currency = "SAR" | "AED" | "USD" | "EUR";
export const supplierRegions = [
  ["RIYADH", "الرياض"],
  ["MAKKAH", "مكة المكرمة"],
  ["MADINAH", "المدينة المنورة"],
  ["QASSIM", "القصيم"],
  ["EASTERN", "المنطقة الشرقية"],
  ["ASIR", "عسير"],
  ["TABUK", "تبوك"],
  ["HAIL", "حائل"],
  ["NORTHERN_BORDERS", "الحدود الشمالية"],
  ["JAZAN", "جازان"],
  ["NAJRAN", "نجران"],
  ["BAHAH", "الباحة"],
  ["JOUF", "الجوف"],
] as const;
export type SupplierRegionCode = (typeof supplierRegions)[number][0];
export type Supplier = {
  id: string;
  name: string;
  tax_number: string | null;
  region_code: SupplierRegionCode | null;
  region_name: string | null;
  verification_status: "UNVERIFIED" | "PENDING" | "VERIFIED" | "REJECTED";
  verification_note: string | null;
  verified_at: string | null;
  verified_by: { id: string; name: string } | null;
  created_at?: string;
};
export type ItemInput = {
  description: string;
  unit: string | null;
  quantity: string;
  unit_price: string;
  discount_amount: string;
  tax_rate: string;
  purchase_order_item_id?: string | null;
  project_budget_line_id?: string | null;
};
export type InvoiceItem = ItemInput & {
  position: number;
  purchase_order_item_id: string | null;
  purchase_order_item_position: number | null;
  project_budget_line_id: string | null;
  budget_line: {
    id: string;
    position: number;
    description: string;
    allocated_amount: string;
    is_active: boolean;
    currency: Currency;
    category: Pick<ExpenseCategory, "id" | "code" | "name">;
  } | null;
  gross_amount: string;
  net_amount: string;
  tax_amount: string;
  total_amount: string;
};
export type Totals = {
  subtotal: string;
  discount_total: string;
  net_total: string;
  tax_total: string;
  grand_total: string;
};
export type DocumentTotals = {
  subtotal: string | null;
  tax_total: string | null;
  grand_total: string | null;
};
export type AuditCheck = {
  code:
    | "DOCUMENT_SUBTOTAL"
    | "DOCUMENT_TAX_TOTAL"
    | "DOCUMENT_GRAND_TOTAL"
    | "EXACT_FILE_DUPLICATE"
    | "POTENTIAL_DUPLICATE"
    | "APPROXIMATE_DUPLICATE"
    | "HISTORICAL_PRICE_ANOMALY"
    | "REGIONAL_SUPPLIER_PRICE"
    | "QR_SOURCE_COMPARISON"
    | "XML_SOURCE_COMPARISON"
    | "PURCHASE_ORDER_HEADER"
    | "PURCHASE_ORDER_LINES"
    | "GOODS_RECEIPT_MATCH"
    | "SUPPLIER_VERIFICATION"
    | "RELATED_FINANCIAL_DOCUMENT"
    | "SPLIT_INVOICE"
    | "PROJECT_BUDGET_RELEVANCE"
    | "PROJECT_BUDGET_CAPACITY";
  label: string;
  status: "PASS" | "WARNING" | "NOT_CHECKED";
  message: string;
  document_value: string | null;
  calculated_value: string | null;
  difference: string | null;
  match_count: number | null;
  source_count?: number | null;
  comparisons?: {
    field: string;
    label: string;
    source_value: string;
    invoice_value: string | null;
    status: "MATCH" | "MISMATCH" | "NOT_COMPARABLE";
  }[];
  price_findings?: {
    position: number;
    description: string;
    unit: string | null;
    status: "PASS" | "WARNING" | "NOT_CHECKED";
    message: string;
    current_unit_price: string | null;
    sample_count: number;
    source_invoice_count: number;
    lookback_days: number;
    median_unit_price: string | null;
    lower_quartile: string | null;
    upper_quartile: string | null;
    alert_threshold: string | null;
    difference_percent: string | null;
    confidence: "MEDIUM" | "HIGH" | null;
  }[];
  regional_findings?: {
    position: number;
    description: string;
    unit: string | null;
    status: "PASS" | "WARNING" | "NOT_CHECKED";
    message: string;
    current_region_code: SupplierRegionCode;
    current_region_name: string;
    current_unit_price: string | null;
    current_region_median: string | null;
    difference_percent: string | null;
    potential_saving: string | null;
    sample_count: number;
    supplier_count: number;
    region_count: number;
    lookback_days: number;
    confidence: "MEDIUM" | "HIGH" | null;
    region_comparisons: {
      region_code: SupplierRegionCode;
      region_name: string;
      median_unit_price: string;
      invoice_count: number;
      supplier_count: number;
      date_from: string;
      date_to: string;
    }[];
  }[];
  policy?: {
    lookback_days: number;
    minimum_invoices: number;
    minimum_increase_percent: string;
    baseline?: "MEDIAN_AND_IQR";
    price_basis?: "AFTER_LINE_DISCOUNT_BEFORE_TAX";
    minimum_suppliers?: number;
    minimum_regions?: number;
    minimum_current_region_invoices?: number;
    benchmark_scope?: "INTERNAL_SUBMITTED_INVOICES";
  };
  comparison_count?: number;
  max_similarity_percent?: number | null;
  similarity_threshold_percent?: number;
  similarity_signals?: {
    code: "SUPPLIER" | "INVOICE_NUMBER" | "DATE" | "TOTAL" | "LINE_CONTENT" | "DOCUMENT_CONTENT";
    label: string;
    available: boolean;
    score_percent: number | null;
    weight_percent: number;
    summary: string;
  }[];
  privacy_note?: string;
  split_analysis?: {
    window_days: number;
    document_count: number;
    combined_total: string;
    approval_threshold: string;
    all_documents_within_threshold: boolean;
    privacy_note: string;
  } | null;
  budget_analysis?: {
    currency: Currency;
    budget_total: string;
    exposure_before_document: string;
    document_effect: string;
    exposure_after_document: string;
    remaining_after_document: string;
    definition: string;
  };
};
export type ExpenseCategory = {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
};
export type BudgetUsage = {
  approved: string;
  committed: string;
  pending: string;
  exposure: string;
  remaining: string;
};
export type ProjectBudgetLine = {
  id: string;
  position: number;
  expense_category: ExpenseCategory;
  description: string;
  unit: string | null;
  planned_quantity: string | null;
  planned_unit_price: string | null;
  allocated_amount: string;
  is_active: boolean;
  usage: BudgetUsage;
};
export type ProjectBudgetView = {
  project: Project;
  currency: Currency;
  budget: {
    id: string;
    revision: number;
    total_amount: string;
    allocated_amount: string;
    unallocated_reserve: string;
    usage: BudgetUsage;
    lines: ProjectBudgetLine[];
    archived_lines: ProjectBudgetLine[];
    updated_at: string;
  } | null;
  definitions: {
    approved: string;
    committed: string;
    pending: string;
    excluded: string;
    currency: string;
  };
};
export type RiskAssessment = {
  score: number;
  level: "LOW" | "MEDIUM" | "HIGH";
  confidence: "LOW" | "MEDIUM" | "HIGH";
  warning_count: number;
  evaluated_count: number;
  total_checks: number;
  factors: {
    code: AuditCheck["code"];
    label: string;
    weight: number;
    message: string;
  }[];
  policy: {
    version: "explainable-review-priority-v1";
    medium_from: number;
    high_from: number;
    maximum_score: number;
  };
  advisory: string;
};
export type InvoiceAudit = {
  revision: number;
  summary: "PASS" | "NEEDS_REVIEW" | "INCOMPLETE";
  blocking: false;
  checks: AuditCheck[];
  risk?: RiskAssessment;
};
export type Calculation = {
  items: InvoiceItem[];
  totals: Totals | null;
  calculation_policy: string;
};
export type FinancialData = {
  supplier: Supplier | null;
  purchase_order: PurchaseOrderReference | null;
  document_type: DocumentType;
  related_document: RelatedDocument | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: Currency | null;
  document_totals: DocumentTotals | null;
  totals: Totals | null;
  items?: InvoiceItem[];
  note?: string | null;
};
export type DocumentType = "INVOICE" | "CREDIT_NOTE" | "DEBIT_NOTE";
export type RelatedDocument = {
  id: string;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: Currency | null;
  grand_total: string | null;
  status: InvoiceStatus;
};
export type ApprovalLimitRow = {
  user: User;
  limits: Record<Currency, string | null>;
};
export type PurchaseOrderReference = {
  id: string;
  number: string;
  order_date: string;
  currency: Currency;
  project: Project;
  supplier: Pick<Supplier, "id" | "name" | "tax_number">;
};
export type PurchaseOrderItem = {
  id: string;
  position: number;
  description: string;
  unit: string | null;
  ordered_quantity: string;
  received_quantity: string;
  unit_price: string;
  tax_rate: string;
  subtotal: string;
  tax_total: string;
  grand_total: string;
};
export type GoodsReceipt = {
  id: string;
  number: string;
  received_date: string;
  note: string | null;
  created_by: { id: string; name: string };
  created_at: string;
  items: {
    purchase_order_item_id: string;
    position: number;
    received_quantity: string;
  }[];
  evidence: { id: string; name: string; media_type: string; size_bytes: number; url: string };
};
export type PurchaseOrder = PurchaseOrderReference & {
  created_by: { id: string; name: string };
  created_at: string;
  items: PurchaseOrderItem[];
  receipts: GoodsReceipt[];
  totals: Pick<Totals, "subtotal" | "tax_total" | "grand_total">;
};
export type Invoice = {
  id: string;
  status: InvoiceStatus;
  revision: number;
  note: string | null;
  created_at: string;
  updated_at: string;
  project: Project;
  created_by: { id: string; name: string };
  attachment: { id: string; name: string; media_type: string; size_bytes: number; url: string };
  workflow?: {
    allowed_actions: (WorkflowAction | "EDIT")[];
    missing_fields: string[];
    submitted_revision: number | null;
    submitted_at: string | null;
    project_approved_revision: number | null;
    approval_authority: {
      currency: Currency | null;
      invoice_total: string | null;
      limit: string | null;
      can_approve: boolean;
      reason: string;
    } | null;
  };
  events?: {
    id: string;
    action: string;
    created_at: string;
    actor_name: string;
    details?: {
      revision?: number;
      before?: FinancialData;
      after?: FinancialData;
      snapshot?: FinancialData;
      comment?: string | null;
      from_status?: InvoiceStatus;
      to_status?: InvoiceStatus;
      submitted_revision?: number;
      audit_snapshot?: InvoiceAudit;
    };
  }[];
  audit?: InvoiceAudit;
} & FinancialData;
export type InvoicePage = { items: Invoice[]; total: number; page: number; page_size: number };
export type DashboardData = {
  generated_at: string;
  currency: Currency;
  project_id: string | null;
  projects: Project[];
  summary: {
    document_count: number;
    approved_document_count: number;
    under_review_document_count: number;
    approved_net: string;
    under_review_net: string;
    exception_count: number;
    high_risk_count: number;
  };
  status_counts: Record<InvoiceStatus, number>;
  monthly_approved_net: { month: string; amount: string }[];
  project_breakdown: {
    project: Project;
    document_count: number;
    approved_net: string;
    under_review_net: string;
    exception_count: number;
  }[];
  supplier_breakdown: {
    supplier_name: string;
    approved_net: string;
    document_count: number;
  }[];
  exception_queue: {
    invoice_id: string;
    invoice_number: string | null;
    project: Project;
    supplier_name: string | null;
    status: InvoiceStatus;
    document_type: DocumentType;
    grand_total: string;
    risk: RiskAssessment;
    top_reason: string;
  }[];
  definitions: {
    approved_net: string;
    under_review_net: string;
    exception_queue: string;
    currency: string;
  };
};
export type ExtractionSuggestion = {
  value: string;
  confidence: number | null;
  source: "OCR" | "PDF_TEXT" | "QR" | "XML";
  page: number | null;
  bbox: number[] | null;
  evidence: string;
  recognition_reads: string[];
  needs_review: true;
};
export type StructuredSource = {
  type: "QR" | "XML";
  location: "DOCUMENT_PAGE" | "UPLOAD" | "PDF_ATTACHMENT";
  page: number | null;
  bbox: number[] | null;
  name: string | null;
  document_type: "ZATCA_TLV" | "Invoice" | "CreditNote" | "DebitNote";
  present_tags: number[];
  fields: Record<string, { value: string; evidence: string }>;
};
export type ExtractionJob = {
  id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "STALE";
  base_revision: number;
  language: "ar" | "en";
  attempts: number;
  is_stale: boolean;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  result: {
    conflict_details?: {
      field: string;
      row: number | null;
      reason: "DISAGREEMENT" | "ROW_TOTAL_MISMATCH";
      current: ExtractionSuggestion | null;
      proposed: ExtractionSuggestion;
    }[];
    guided_reading?: {
      status: "COMPLETED" | "PARTIAL" | "UNAVAILABLE";
      attempted: number;
      completed: number;
      table_sections: number;
      recovered_tokens: number;
    } | null;
    local_understanding?: {
      status: "COMPLETED" | "PARTIAL" | "UNAVAILABLE" | "NOT_APPLICABLE";
      pages: number;
      added_fields: number;
      confirmed_fields: number;
      added_rows: number;
      conflicts: number;
      rejected_values: number;
      seconds: number;
    } | null;
    image_preparation?: {
      page: number;
      method: "ORIGINAL" | "PERSPECTIVE_CORRECTED";
      reread_regions: number;
      rotation?: 0 | 90 | 180 | 270;
      curvature_corrected?: boolean;
    }[];
    reader_version?: string;
    page_routes?: {
      page: number;
      method: "PDF_TEXT" | "OCR" | "BLANK";
      reason: string;
      image_coverage: number;
    }[];
    text?: string;
    tokens?: {
      text: string;
      confidence: number | null;
      source: "PDF_TEXT" | "OCR";
      page: number;
      bbox: number[];
      reading_order: number;
      line_number: number;
    }[];
    fields: Record<string, ExtractionSuggestion>;
    items: Record<string, ExtractionSuggestion>[];
    warnings: string[];
    requires_human_review: true;
    structured_sources?: StructuredSource[];
  } | null;
};
export type WorkflowAction = "SUBMIT" | "APPROVE" | "REQUEST_CHANGES" | "REJECT";
export type InvoiceStatus =
  "DRAFT" | "PROJECT_REVIEW" | "FINANCE_REVIEW" | "CHANGES_REQUESTED" | "APPROVED" | "REJECTED";
export const statusLabels: Record<InvoiceStatus, string> = {
  DRAFT: "مسودة خاصة",
  PROJECT_REVIEW: "مراجعة مدير المشروع",
  FINANCE_REVIEW: "مراجعة المالية",
  CHANGES_REQUESTED: "مطلوب تعديل",
  APPROVED: "معتمدة",
  REJECTED: "مرفوضة",
};
export const eventLabels: Record<string, string> = {
  EXTRACTION_REQUESTED: "طلب قراءة الفاتورة",
  EXTRACTION_REVIEWED: "تأكيد مراجعة اقتراحات الاستخراج",
  DRAFT_CREATED: "إنشاء المسودة",
  FILE_ATTACHED: "حفظ الملف الأصلي",
  INVOICE_SUBMITTED: "تأكيد البيانات وإرسال الفاتورة",
  INVOICE_RESUBMITTED: "إعادة إرسال الفاتورة",
  PROJECT_APPROVED: "موافقة مدير المشروع",
  FINANCE_APPROVED: "اعتماد المالية",
  CHANGES_REQUESTED: "طلب تعديل الفاتورة",
  INVOICE_REJECTED: "رفض الفاتورة",
};
export const roles = {
  EMPLOYEE: "موظف المشتريات",
  PROJECT_MANAGER: "مدير المشروع",
  FINANCE_MANAGER: "مدير المالية",
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function validationMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "تعذر إكمال الطلب. راجع البيانات وحاول مجددًا.";
  const names: Record<string, string> = {
    quantity: "الكمية",
    unit_price: "سعر الوحدة",
    discount_amount: "الخصم",
    tax_rate: "نسبة الضريبة",
    description: "وصف البند",
    currency: "العملة",
    invoice_date: "تاريخ الفاتورة",
    invoice_number: "رقم الفاتورة",
    name: "اسم المورد",
    tax_number: "الرقم الضريبي",
    unit: "الوحدة",
    note: "الملاحظة",
    items: "البنود",
    code: "رمز الفئة",
    total_amount: "إجمالي الميزانية",
    allocated_amount: "مخصص البند",
    planned_quantity: "الكمية المخططة",
    planned_unit_price: "سعر الوحدة المخطط",
    expense_category_id: "فئة المصروف",
    email: "البريد الإلكتروني",
    temporary_password: "كلمة المرور المؤقتة",
    role: "الدور",
    members: "أعضاء المشروع",
  };
  return detail
    .map((error) => {
      const location = error.loc || [];
      const field = names[location.at(-1)] || "البيانات المدخلة";
      const index = location.indexOf("items");
      const line =
        index >= 0 && typeof location[index + 1] === "number"
          ? ` في البند ${location[index + 1] + 1}`
          : "";
      return /[\u0600-\u06ff]/.test(error.msg || "")
        ? error.msg.replace(/^Value error, /, "")
        : `راجع ${field}${line} وحدود القيمة المسموحة.`;
    })
    .join(" ");
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "تعذر الاتصال. تحقق من الشبكة ثم حاول مجددًا.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login" && typeof window !== "undefined") {
      window.location.assign("/login");
    }
    throw new ApiError(response.status, validationMessage(data.detail));
  }
  return data as T;
}
