"use client";
import { useEffect, useState } from "react";
import { FolderKanban, LoaderCircle } from "lucide-react";
import { api, type Project } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api<Project[]>("/projects")
      .then((data) => {
        if (active) setProjects(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  return (
    <div className="page-container">
      <div className="page-heading">
        <div>
          <span className="eyebrow">نطاق عملك</span>
          <h1>المشاريع</h1>
          <p>المشاريع المتاحة لك حسب تكليفك وصلاحياتك.</p>
        </div>
      </div>
      {error ? (
        <div className="surface inline-state">
          <p role="alert">{error}</p>
          <Button variant="outline" onClick={() => setAttempt((n) => n + 1)}>
            إعادة المحاولة
          </Button>
        </div>
      ) : !projects ? (
        <div className="inline-state">
          <LoaderCircle className="animate-spin" />
          جارٍ تحميل المشاريع…
        </div>
      ) : !projects.length ? (
        <div className="surface inline-state">
          <FolderKanban size={30} />
          <h2>لا توجد مشاريع متاحة</h2>
          <p>تظهر المشاريع هنا بعد ربط حسابك بها.</p>
        </div>
      ) : (
        <div className="project-grid">
          {projects.map((project) => (
            <article key={project.id} className="surface project-card">
              <div className="project-card-top">
                <span className="metric-icon">
                  <FolderKanban size={25} />
                </span>
                <span className="project-code" dir="ltr">
                  {project.code}
                </span>
              </div>
              <h2>{project.name}</h2>
              <p>
                <span className="status-dot" />
                مشروع متاح ضمن صلاحياتك
              </p>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
