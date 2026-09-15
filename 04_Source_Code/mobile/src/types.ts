export type UserRole = "EMPLOYEE" | "PROJECT_MANAGER" | "FINANCE_MANAGER";

export type User = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
};

export type AuthSession = {
  user: User;
  csrf_token: string;
  expires_at: string;
};

export type MobileLoginResult = AuthSession & {
  access_token: string;
  token_type: "bearer";
};

export type Project = { id: string; name: string; code: string };

export type InvoiceStatus =
  | "DRAFT"
  | "PROJECT_REVIEW"
  | "FINANCE_REVIEW"
  | "CHANGES_REQUESTED"
  | "APPROVED"
  | "REJECTED";

export type AuditCheck = {
  code: string;
  label: string;
  status: "PASS" | "WARNING" | "NOT_CHECKED";
  message: string;
};

export type RiskAssessment = {
  score: number;
  level: "LOW" | "MEDIUM" | "HIGH";
  confidence: "LOW" | "MEDIUM" | "HIGH";
  warning_count: number;
  evaluated_count: number;
  total_checks: number;
  advisory: string;
  factors: { code: string; label: string; weight: number; message: string }[];
};

export type Invoice = {
  id: string;
  status: InvoiceStatus;
  revision: number;
  note: string | null;
  created_at: string;
  project: Project;
  created_by: { id: string; name: string };
  attachment: {
    id: string;
    name: string;
    media_type: string;
    size_bytes: number;
    url: string;
  };
  document_type: "INVOICE" | "CREDIT_NOTE" | "DEBIT_NOTE";
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string | null;
  supplier: { id: string; name: string; tax_number: string | null } | null;
  totals: { grand_total: string; tax_total: string; net_total: string } | null;
  audit?: {
    summary: "PASS" | "NEEDS_REVIEW" | "INCOMPLETE";
    checks: AuditCheck[];
    risk?: RiskAssessment;
  };
  events?: {
    id: string;
    action: string;
    actor_name: string;
    created_at: string;
  }[];
};

export type InvoicePage = {
  items: Invoice[];
  total: number;
  page: number;
  page_size: number;
};
