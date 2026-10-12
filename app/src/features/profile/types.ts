// Mirrors the pydantic models in api/jobhunt/profile/router.py (see /openapi.json).

export type ResumeFile = {
  id: number;
  name: string;
  filename: string | null;
  text: string;
  origin: "upload" | "vault";
  is_selected: boolean;
  created_at: string;
  text_length: number;
};
