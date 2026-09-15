"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  FolderPlus,
  KeyRound,
  LoaderCircle,
  Save,
  ShieldCheck,
  UserPlus,
  UsersRound,
} from "lucide-react";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError, roles, type AdminProject, type AdminUser, type User } from "@/lib/api";

type Role = User["role"];
const roleOptions: Role[] = ["EMPLOYEE", "PROJECT_MANAGER", "FINANCE_MANAGER"];

export default function AdministrationPage() {
  const { user, csrf_token } = useSession();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [projects, setProjects] = useState<AdminProject[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [newUser, setNewUser] = useState({
    name: "",
    email: "",
    role: "EMPLOYEE" as Role,
    temporary_password: "",
  });
  const [newProject, setNewProject] = useState({ name: "", code: "" });
  const [resetPasswords, setResetPasswords] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    const [userRows, projectRows] = await Promise.all([
      api<AdminUser[]>("/administration/users"),
      api<AdminProject[]>("/administration/projects"),
    ]);
    setUsers(userRows);
    setProjects(projectRows);
  }, []);

  useEffect(() => {
    if (user.role !== "FINANCE_MANAGER") {
      setLoading(false);
      return;
    }
    let active = true;
    refresh()
      .catch((failure) => active && setError(failure.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [refresh, user.role]);

  async function mutate(key: string, action: () => Promise<unknown>, success: string) {
    setSaving(key);
    setError("");
    setMessage("");
    try {
      await action();
      await refresh();
      setMessage(success);
      return true;
    } catch (failure) {
      setError((failure as Error).message);
      if (failure instanceof ApiError && failure.status === 409) await refresh().catch(() => null);
      return false;
    } finally {
      setSaving("");
    }
  }

  async function createUser(event: FormEvent) {
    event.preventDefault();
    const saved = await mutate(
      "new-user",
      () =>
        api("/administration/users", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
          body: JSON.stringify(newUser),
        }),
      "أُنشئ الحساب وسُجلت العملية. أرسل كلمة المرور المؤقتة للمستخدم عبر قناة آمنة.",
    );
    if (saved) setNewUser({ name: "", email: "", role: "EMPLOYEE", temporary_password: "" });
  }

  async function saveUser(row: AdminUser) {
    await mutate(
      `user-${row.id}`,
      () =>
        api(`/administration/users/${row.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
          body: JSON.stringify({
            revision: row.revision,
            name: row.name,
            role: row.role,
            is_active: row.is_active,
          }),
        }),
      "حُفظت بيانات الحساب وسُجل التغيير.",
    );
  }

  async function resetPassword(row: AdminUser) {
    const temporaryPassword = resetPasswords[row.id] || "";
    const saved = await mutate(
      `password-${row.id}`,
      () =>
        api(`/administration/users/${row.id}/reset-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
          body: JSON.stringify({
            revision: row.revision,
            temporary_password: temporaryPassword,
          }),
        }),
      "أُعيد ضبط كلمة المرور وأُغلقت جلسات المستخدم السابقة.",
    );
    if (saved) setResetPasswords((current) => ({ ...current, [row.id]: "" }));
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    const saved = await mutate(
      "new-project",
      () =>
        api("/administration/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
          body: JSON.stringify(newProject),
        }),
      "أُنشئ المشروع وسُجلت العملية. أضف أعضاءه من البطاقة أدناه.",
    );
    if (saved) setNewProject({ name: "", code: "" });
  }

  async function saveProject(row: AdminProject) {
    await mutate(
      `project-${row.id}`,
      () =>
        api(`/administration/projects/${row.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
          body: JSON.stringify({
            revision: row.revision,
            name: row.name,
            code: row.code,
            is_active: row.is_active,
          }),
        }),
      "حُفظت بيانات المشروع وسُجل التغيير.",
    );
  }

  async function saveMembers(row: AdminProject) {
    await mutate(
      `members-${row.id}`,
      () =>
        api(`/administration/projects/${row.id}/members`, {
          method: "PUT",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
          body: JSON.stringify({
            revision: row.revision,
            members: row.members.map((member) => member.id),
          }),
        }),
      "حُفظ أعضاء المشروع وطُبقت صلاحياتهم فورًا.",
    );
  }

  function patchUser(id: string, patch: Partial<AdminUser>) {
    setUsers(
      (current) => current?.map((row) => (row.id === id ? { ...row, ...patch } : row)) || null,
    );
  }

  function patchProject(id: string, patch: Partial<AdminProject>) {
    setProjects(
      (current) => current?.map((row) => (row.id === id ? { ...row, ...patch } : row)) || null,
    );
  }

  function toggleMember(project: AdminProject, candidate: AdminUser, checked: boolean) {
    const members = checked
      ? [
          ...project.members,
          {
            id: candidate.id,
            name: candidate.name,
            email: candidate.email,
            role: candidate.role,
            is_active: candidate.is_active,
            membership_role:
              candidate.role === "PROJECT_MANAGER" ? ("MANAGER" as const) : ("MEMBER" as const),
          },
        ]
      : project.members.filter((member) => member.id !== candidate.id);
    patchProject(project.id, { members });
  }

  if (user.role !== "FINANCE_MANAGER") {
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <ShieldCheck size={28} />
          <h1>إدارة النظام متاحة لمدير المالية</h1>
          <p>تتحقق الخدمة من الصلاحية أيضًا قبل قراءة البيانات أو تعديلها.</p>
        </div>
      </div>
    );
  }

  const candidates = (users || []).filter((row) => row.is_active && row.role !== "FINANCE_MANAGER");

  return (
    <div className="page-container administration-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">إعداد مساحة العمل</span>
          <h1>المشاريع والمستخدمون</h1>
          <p>إدارة الحسابات والأدوار وعضويات المشاريع مع سجل تدقيق وحماية للمهام المفتوحة.</p>
        </div>
        <span className="feature-icon">
          <UsersRound size={26} />
        </span>
      </div>

      <div className="surface administration-note">
        <ShieldCheck size={20} />
        <p>
          لا يسمح النظام بتعطيل آخر مدير مالية، أو إزالة مسؤول عن فاتورة قابلة للتعديل، أو ترك
          فاتورة في مراجعة المشروع بلا مدير نشط.
        </p>
      </div>
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className="success-box" role="status">
          {message}
        </div>
      )}
      {loading || !users || !projects ? (
        <div className="surface inline-state">
          <LoaderCircle className="animate-spin" /> جارٍ تحميل إعدادات النظام…
        </div>
      ) : (
        <>
          <section className="administration-section" aria-labelledby="users-title">
            <div className="section-title">
              <div>
                <span className="eyebrow">{users.length} حسابات داخل الشركة</span>
                <h2 id="users-title">المستخدمون والأدوار</h2>
              </div>
              <UserPlus />
            </div>
            <form className="surface administration-create" onSubmit={createUser}>
              <div className="field">
                <label htmlFor="new-user-name">اسم المستخدم</label>
                <Input
                  id="new-user-name"
                  required
                  minLength={2}
                  maxLength={120}
                  value={newUser.name}
                  onChange={(event) => setNewUser({ ...newUser, name: event.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="new-user-email">البريد الإلكتروني</label>
                <Input
                  id="new-user-email"
                  dir="ltr"
                  type="email"
                  required
                  value={newUser.email}
                  onChange={(event) => setNewUser({ ...newUser, email: event.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="new-user-role">الدور</label>
                <select
                  id="new-user-role"
                  className="form-field"
                  value={newUser.role}
                  onChange={(event) => setNewUser({ ...newUser, role: event.target.value as Role })}
                >
                  {roleOptions.map((role) => (
                    <option key={role} value={role}>
                      {roles[role]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="new-user-password">كلمة المرور المؤقتة</label>
                <Input
                  id="new-user-password"
                  dir="ltr"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={12}
                  value={newUser.temporary_password}
                  onChange={(event) =>
                    setNewUser({ ...newUser, temporary_password: event.target.value })
                  }
                  placeholder="12 خانة مع رقم ورمز"
                />
              </div>
              <Button type="submit" disabled={saving === "new-user"}>
                {saving === "new-user" ? <LoaderCircle className="animate-spin" /> : <UserPlus />}
                إنشاء الحساب
              </Button>
            </form>

            <div className="administration-cards">
              {users.map((row) => {
                const ownAccount = row.id === user.id;
                return (
                  <article
                    className="surface administration-card"
                    data-user-email={row.email}
                    key={row.id}
                  >
                    <div className="administration-card-heading">
                      <div>
                        <span className={`account-state ${row.is_active ? "active" : "inactive"}`}>
                          {row.is_active ? "نشط" : "معطل"}
                        </span>
                        {ownAccount && <span className="draft-badge">حسابك</span>}
                      </div>
                      <small>
                        {row.memberships.length
                          ? `${row.memberships.length} عضويات مشاريع`
                          : "بلا عضوية مشروع"}
                      </small>
                    </div>
                    <div className="administration-edit-grid">
                      <div className="field">
                        <label htmlFor={`user-name-${row.id}`}>الاسم</label>
                        <Input
                          id={`user-name-${row.id}`}
                          disabled={ownAccount}
                          value={row.name}
                          onChange={(event) => patchUser(row.id, { name: event.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`user-role-${row.id}`}>الدور</label>
                        <select
                          id={`user-role-${row.id}`}
                          className="form-field"
                          disabled={ownAccount}
                          value={row.role}
                          onChange={(event) =>
                            patchUser(row.id, { role: event.target.value as Role })
                          }
                        >
                          {roleOptions.map((role) => (
                            <option key={role} value={role}>
                              {roles[role]}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <p className="administration-email" dir="ltr">
                      {row.email}
                    </p>
                    <div className="membership-chips">
                      {row.memberships.map((membership) => (
                        <span key={membership.project.id}>
                          {membership.project.code} ·{" "}
                          {membership.membership_role === "MANAGER" ? "مدير" : "عضو"}
                        </span>
                      ))}
                    </div>
                    <div className="administration-actions">
                      <label className="state-toggle">
                        <input
                          type="checkbox"
                          disabled={ownAccount}
                          checked={row.is_active}
                          onChange={(event) =>
                            patchUser(row.id, { is_active: event.target.checked })
                          }
                        />
                        حساب نشط
                      </label>
                      {!ownAccount && (
                        <Button
                          size="sm"
                          variant="outline"
                          type="button"
                          disabled={saving === `user-${row.id}`}
                          onClick={() => saveUser(row)}
                        >
                          <Save size={16} /> حفظ الحساب
                        </Button>
                      )}
                    </div>
                    {!ownAccount && (
                      <div className="password-reset">
                        <div className="field">
                          <label htmlFor={`reset-${row.id}`}>كلمة مرور مؤقتة جديدة</label>
                          <Input
                            id={`reset-${row.id}`}
                            dir="ltr"
                            type="password"
                            autoComplete="new-password"
                            minLength={12}
                            value={resetPasswords[row.id] || ""}
                            onChange={(event) =>
                              setResetPasswords((current) => ({
                                ...current,
                                [row.id]: event.target.value,
                              }))
                            }
                          />
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={saving === `password-${row.id}` || !resetPasswords[row.id]}
                          onClick={() => resetPassword(row)}
                        >
                          <KeyRound size={16} /> إعادة الضبط
                        </Button>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          <section className="administration-section" aria-labelledby="projects-title">
            <div className="section-title">
              <div>
                <span className="eyebrow">{projects.length} مشاريع داخل الشركة</span>
                <h2 id="projects-title">المشاريع وعضوياتها</h2>
              </div>
              <FolderPlus />
            </div>
            <form className="surface administration-create project-create" onSubmit={createProject}>
              <div className="field">
                <label htmlFor="new-project-name">اسم المشروع</label>
                <Input
                  id="new-project-name"
                  required
                  minLength={2}
                  maxLength={200}
                  value={newProject.name}
                  onChange={(event) => setNewProject({ ...newProject, name: event.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="new-project-code">رمز المشروع</label>
                <Input
                  id="new-project-code"
                  dir="ltr"
                  required
                  maxLength={40}
                  value={newProject.code}
                  onChange={(event) =>
                    setNewProject({ ...newProject, code: event.target.value.toUpperCase() })
                  }
                  placeholder="PRJ-002"
                />
              </div>
              <Button type="submit" disabled={saving === "new-project"}>
                {saving === "new-project" ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <FolderPlus />
                )}
                إنشاء المشروع
              </Button>
            </form>

            <div className="project-administration-list">
              {projects.map((project) => (
                <article
                  className="surface project-administration-card"
                  data-project-code={project.code}
                  key={project.id}
                >
                  <div className="project-administration-heading">
                    <div className="administration-edit-grid">
                      <div className="field">
                        <label htmlFor={`project-name-${project.id}`}>اسم المشروع</label>
                        <Input
                          id={`project-name-${project.id}`}
                          value={project.name}
                          onChange={(event) =>
                            patchProject(project.id, { name: event.target.value })
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`project-code-${project.id}`}>الرمز</label>
                        <Input
                          id={`project-code-${project.id}`}
                          dir="ltr"
                          value={project.code}
                          onChange={(event) =>
                            patchProject(project.id, { code: event.target.value.toUpperCase() })
                          }
                        />
                      </div>
                    </div>
                    <div className="administration-actions project-actions">
                      <label className="state-toggle">
                        <input
                          type="checkbox"
                          checked={project.is_active}
                          onChange={(event) =>
                            patchProject(project.id, { is_active: event.target.checked })
                          }
                        />
                        مشروع نشط
                      </label>
                      <Button
                        size="sm"
                        variant="outline"
                        type="button"
                        disabled={saving === `project-${project.id}`}
                        onClick={() => saveProject(project)}
                      >
                        <Save size={16} /> حفظ المشروع
                      </Button>
                    </div>
                  </div>
                  <fieldset className="project-members" disabled={!project.is_active}>
                    <legend>أعضاء المشروع</legend>
                    {candidates.length ? (
                      <div className="member-picker">
                        {candidates.map((candidate) => (
                          <label key={candidate.id}>
                            <input
                              type="checkbox"
                              checked={project.members.some((member) => member.id === candidate.id)}
                              onChange={(event) =>
                                toggleMember(project, candidate, event.target.checked)
                              }
                            />
                            <span>
                              <strong>{candidate.name}</strong>
                              <small>{roles[candidate.role]}</small>
                            </span>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <p className="empty-copy">أنشئ موظفًا أو مدير مشروع نشطًا لإضافته.</p>
                    )}
                    <Button
                      size="sm"
                      type="button"
                      disabled={!project.is_active || saving === `members-${project.id}`}
                      onClick={() => saveMembers(project)}
                    >
                      <UsersRound size={16} /> حفظ الأعضاء
                    </Button>
                  </fieldset>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
