"use client";

import { ChevronsUpDownIcon, XIcon } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export type ComboOption = { id: string; label: string; color?: string };

export function CreatableCombobox({
  label,
  mode,
  options,
  value,
  onChange,
  onCreate,
  placeholder,
}: {
  label: string;
  mode: "single" | "multi";
  options: ComboOption[];
  value: string[];
  onChange: (value: string[]) => void;
  onCreate?: (name: string) => Promise<ComboOption | null>;
  placeholder: string;
}) {
  const buttonId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const selected = options.filter((option) => value.includes(option.id));
  const trimmed = query.trim();
  const exact = options.some((option) => option.label.toLowerCase() === trimmed.toLowerCase());
  const showCreate = Boolean(onCreate) && trimmed.length > 0 && !exact;

  function pick(id: string) {
    if (mode === "single") {
      onChange(value[0] === id ? [] : [id]);
      setOpen(false);
      setQuery("");
      return;
    }
    onChange(value.includes(id) ? value.filter((item) => item !== id) : [...value, id]);
  }

  async function create() {
    if (!onCreate || !trimmed || creating) return;
    setCreating(true);
    const created = await onCreate(trimmed);
    setCreating(false);
    if (!created) return;
    onChange(mode === "single" ? [created.id] : [...value, created.id]);
    setQuery("");
    if (mode === "single") setOpen(false);
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={buttonId}>{label}</Label>
      {mode === "multi" && selected.length > 0 && (
        <ul className="flex flex-wrap gap-1" aria-label={`Selected ${label}`}>
          {selected.map((option) => (
            <li
              key={option.id}
              className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs"
            >
              {option.color && <span className="size-2 rounded-full" style={{ backgroundColor: option.color }} />}
              {option.label}
              <button
                type="button"
                aria-label={`Remove ${option.label}`}
                className="rounded-sm hover:text-foreground"
                onClick={() => onChange(value.filter((id) => id !== option.id))}
              >
                <XIcon className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <Popover open={open} onOpenChange={setOpen} modal>
        <PopoverTrigger asChild>
          <Button
            id={buttonId}
            type="button"
            variant="outline"
            aria-expanded={open}
            className="w-full justify-between px-2 font-normal"
          >
            <span className="truncate text-muted-foreground">
              {mode === "single" && selected[0] ? (
                <span className="text-foreground">{selected[0].label}</span>
              ) : (
                placeholder
              )}
            </span>
            <ChevronsUpDownIcon className="size-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent>
          <Command>
            <CommandInput placeholder={placeholder} value={query} onValueChange={setQuery} />
            <CommandList>
              <CommandEmpty>{showCreate ? null : "No matches"}</CommandEmpty>
              <CommandGroup>
                {options.map((option) => (
                  <CommandItem
                    key={option.id}
                    value={option.label}
                    data-checked={value.includes(option.id) ? true : undefined}
                    onSelect={() => pick(option.id)}
                  >
                    {option.color && (
                      <span className="size-2 rounded-full" style={{ backgroundColor: option.color }} />
                    )}
                    {option.label}
                  </CommandItem>
                ))}
                {showCreate && (
                  <CommandItem value={trimmed} onSelect={() => void create()} disabled={creating}>
                    Create “{trimmed}”
                  </CommandItem>
                )}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
