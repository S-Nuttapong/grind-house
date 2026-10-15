"use client";

import { Trash2Icon, UploadIcon } from "lucide-react";
import { useState, useTransition, type DragEvent } from "react";
import { toast } from "sonner";

import { deleteResume, selectResume, uploadResume } from "@/features/profile/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { ResumeFile } from "@/features/profile/types";
import { cn } from "@/lib/utils";

const ACCEPT = ".pdf,.md,.txt,.json";

export function ResumePanel({ resumes }: { resumes: ResumeFile[] }) {
  const [previewId, setPreviewId] = useState<number | null>(resumes.find((resume) => resume.is_selected)?.id ?? resumes[0]?.id ?? null);
  const [dragging, setDragging] = useState(false);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [isPending, startTransition] = useTransition();
  const preview = resumes.find((resume) => resume.id === previewId) ?? null;
  const confirming = resumes.find((resume) => resume.id === confirmId) ?? null;
  const selectedId = resumes.find((resume) => resume.is_selected)?.id ?? null;
  const [chosenId, setChosenId] = useState<number | null>(selectedId);
  const [trackedSelectedId, setTrackedSelectedId] = useState(selectedId);
  if (selectedId !== trackedSelectedId) {
    setTrackedSelectedId(selectedId);
    setChosenId(selectedId);
  }

  function send(file: File) {
    const body = new FormData();
    body.append("file", file);
    startTransition(async () => {
      const result = await uploadResume(body);
      if (result.ok) toast.success("Resume uploaded");
      else toast.error(result.error);
    });
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) send(file);
  }

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-4">
        <label
          htmlFor="resume-file"
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-8 text-center text-sm text-muted-foreground",
            dragging && "border-primary bg-accent",
          )}
        >
          <UploadIcon className="size-5" />
          <span>Drop a resume here, or click to choose a .pdf, .md, .txt, or .json file under 5 MB.</span>
          <input
            id="resume-file"
            type="file"
            accept={ACCEPT}
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) send(file);
              event.target.value = "";
            }}
          />
        </label>
        {resumes.length === 0 ? (
          <p className="text-sm text-muted-foreground">No resumes yet. Upload one, then select it for scoring.</p>
        ) : (
          <RadioGroup
            aria-label="Selected resume"
            value={chosenId === null ? "" : String(chosenId)}
            onValueChange={(value) => {
              const id = Number(value);
              setChosenId(id);
              startTransition(async () => {
                const result = await selectResume(id);
                if (result.ok) toast.success("Resume selected");
                else {
                  setChosenId(selectedId);
                  toast.error(result.error);
                }
              });
            }}
            className="gap-2"
          >
            {resumes.map((resume) => (
              <div key={resume.id} className={cn("flex items-center gap-3 rounded-lg border px-3 py-2", previewId === resume.id && "border-primary/50")}>
                <RadioGroupItem id={`resume-${resume.id}`} value={String(resume.id)} />
                <div className="min-w-0 flex-1">
                  <Label htmlFor={`resume-${resume.id}`} className="truncate font-normal">
                    {resume.name}
                  </Label>
                  <button type="button" className="mt-1 text-xs text-primary underline-offset-4 hover:underline" onClick={() => setPreviewId(resume.id)}>
                    Preview extracted text
                  </button>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <Badge variant="outline" className="capitalize">
                      {resume.origin}
                    </Badge>
                    {resume.text_length.toLocaleString()} characters
                  </span>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Delete ${resume.name}`}
                  disabled={isPending}
                  onClick={() => setConfirmId(resume.id)}
                >
                  <Trash2Icon />
                </Button>
              </div>
            ))}
          </RadioGroup>
        )}
      </div>
      <section aria-labelledby="resume-preview-heading" className="rounded-xl border bg-card p-4">
        <h2 id="resume-preview-heading" className="text-sm font-semibold">
          Extracted text
        </h2>
        {preview ? (
          <pre className="mt-3 max-h-[36rem] overflow-auto text-sm whitespace-pre-wrap">{preview.text || "No text could be extracted."}</pre>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">Choose a resume to preview the text scoring will use.</p>
        )}
      </section>
      <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirmId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {confirming?.name}?</DialogTitle>
            <DialogDescription>This removes the stored text. The original file is not on this machine.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmId(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={isPending}
              onClick={() => {
                if (!confirming) return;
                startTransition(async () => {
                  const result = await deleteResume(confirming.id);
                  if (result.ok) {
                    toast.success("Resume deleted");
                    if (previewId === confirming.id) setPreviewId(null);
                    setConfirmId(null);
                  } else toast.error(result.error);
                });
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
