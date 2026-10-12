import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import type { BragDoc } from "@/features/brag/types";

export function BragDocCard({
  doc,
  onEdit,
  onDelete,
}: {
  doc: BragDoc;
  onEdit: (doc: BragDoc) => void;
  onDelete: (doc: BragDoc) => void;
}) {
  const where = [doc.company, doc.role].filter(Boolean).join(" · ");
  return (
    <article className="space-y-3 rounded-xl bg-card p-4 text-sm ring-1 ring-foreground/10">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h3 className="text-base font-medium leading-snug">{doc.title}</h3>
          <p className="text-muted-foreground">
            <time dateTime={doc.date}>{doc.date}</time>
            {where && <span> · {where}</span>}
            {doc.impact !== null && <span> · Impact {doc.impact}</span>}
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button type="button" variant="outline" size="sm" onClick={() => onEdit(doc)}>
            Edit
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => onDelete(doc)}>
            Delete
          </Button>
        </div>
      </div>
      {doc.tags.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Tags">
          {doc.tags.map((tag) => (
            <li
              key={tag.id}
              className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2 py-0.5 text-xs"
            >
              <span className="size-2 rounded-full" style={{ backgroundColor: tag.color_hex }} />
              {tag.name}
            </li>
          ))}
        </ul>
      )}
      {doc.metrics.length > 0 && (
        <ul className="space-y-1">
          {doc.metrics.map((metric) => (
            <li key={metric.id}>
              <span className="font-medium">{metric.name}:</span> {metric.value}
            </li>
          ))}
        </ul>
      )}
      {doc.description_md.trim() && <Markdown>{doc.description_md}</Markdown>}
      {doc.attachments.length > 0 && (
        <ul className="space-y-1">
          {doc.attachments.map((item) => (
            <li key={item.id}>
              <a href={item.link} target="_blank" rel="noopener noreferrer" className="text-primary underline-offset-4 hover:underline">
                {item.link}
              </a>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
