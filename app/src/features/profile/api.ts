import { request } from "@/lib/apiClient";
import type { ResumeFile } from "@/features/profile/types";

export function fetchSummary(): Promise<{ body_md: string }> {
  return request<{ body_md: string }>("/api/profile/summary");
}

export function saveSummary(bodyMd: string): Promise<{ body_md: string }> {
  return request<{ body_md: string }>("/api/profile/summary", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ body_md: bodyMd }),
  });
}

export function fetchResumes(): Promise<ResumeFile[]> {
  return request<ResumeFile[]>("/api/resumes");
}

export function uploadResumeFile(file: File): Promise<ResumeFile> {
  const body = new FormData();
  body.append("file", file, file.name);
  return request<ResumeFile>("/api/resumes", { method: "POST", body });
}

export function selectResumeFile(id: number): Promise<ResumeFile> {
  return request<ResumeFile>(`/api/resumes/${id}/select`, { method: "POST" });
}

export function removeResume(id: number): Promise<void> {
  return request<void>(`/api/resumes/${id}`, { method: "DELETE" });
}
