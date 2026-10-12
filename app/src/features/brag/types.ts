// Mirrors the pydantic models in api/jobhunt/brag/router.py (see /openapi.json).

export type Tag = {
  id: number;
  name: string;
  color_hex: string;
};

export type MetricKey = {
  id: number;
  name: string;
};

export type BragMetric = {
  id: number;
  metric_key_id: number;
  name: string;
  value: string;
  position: number;
};

export type BragAttachment = {
  id: number;
  type: "url";
  link: string;
  position: number;
};

export type BragDoc = {
  id: string;
  title: string;
  date: string;
  quarter: string;
  company: string | null;
  role: string | null;
  description_md: string;
  origin: "vault" | "ui";
  impact: number | null;
  updated_at: string;
  tags: Tag[];
  metrics: BragMetric[];
  attachments: BragAttachment[];
};

export type BragDocInput = {
  title: string;
  date: string;
  company: string | null;
  role: string | null;
  description_md: string;
  impact: number | null;
  tag_ids: number[];
  metrics: { metric_key_id: number; value: string }[];
  attachments: { type: "url"; link: string }[];
};
