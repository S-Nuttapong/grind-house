"use server";

import { refresh } from "next/cache";

import { ApiError } from "@/lib/apiClient";
import { createBragDoc, createMetricKey as storeMetricKey, createTag as storeTag, removeBragDoc, updateBragDoc } from "@/features/brag/api";
import type { BragDocInput, MetricKey, Tag } from "@/features/brag/types";

export type ActionResult = { ok: true } | { ok: false; error: string };
export type TagResult = { ok: true; tag: Tag } | { ok: false; error: string };
export type MetricKeyResult = { ok: true; metricKey: MetricKey } | { ok: false; error: string };

const LINK = /^https?:\/\/\S+$/;

export async function saveBragDoc(input: BragDocInput, id: string | null): Promise<ActionResult> {
  const error = validate(input);
  if (error) return { ok: false, error };
  return run(() => (id ? updateBragDoc(id, input) : createBragDoc(input)));
}

export async function deleteBragDoc(id: string): Promise<ActionResult> {
  if (!id.trim()) return { ok: false, error: "Missing brag doc" };
  return run(() => removeBragDoc(id));
}

export async function createTag(name: string): Promise<TagResult> {
  const cleaned = name.trim();
  if (!cleaned || cleaned.length > 60) return { ok: false, error: "Tag name is too long" };
  try {
    const tag = await storeTag(cleaned);
    return { ok: true, tag };
  } catch (error) {
    return { ok: false, error: message(error) };
  }
}

export async function createMetricKey(name: string): Promise<MetricKeyResult> {
  const cleaned = name.trim();
  if (!cleaned || cleaned.length > 80) return { ok: false, error: "Metric name is too long" };
  try {
    const metricKey = await storeMetricKey(cleaned);
    return { ok: true, metricKey };
  } catch (error) {
    return { ok: false, error: message(error) };
  }
}

function validate(input: BragDocInput): string | null {
  if (!input.title.trim() || input.title.trim().length > 200) return "Title is required";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input.date)) return "Pick a date";
  if (input.description_md.length > 20_000) return "The write-up is too long";
  if (input.metrics.length > 30) return "Too many metrics";
  if (input.metrics.some((metric) => !metric.value.trim() || metric.metric_key_id <= 0)) {
    return "Each metric needs a key and a value";
  }
  if (input.attachments.some((item) => !LINK.test(item.link.trim()))) {
    return "Links must start with http:// or https://";
  }
  return null;
}

async function run(work: () => Promise<unknown>): Promise<ActionResult> {
  try {
    await work();
  } catch (error) {
    console.error("brag doc action failed", error);
    return { ok: false, error: message(error) };
  }
  refresh();
  return { ok: true };
}

function message(error: unknown): string {
  return error instanceof ApiError ? error.message : "Could not save. Is the API running?";
}
