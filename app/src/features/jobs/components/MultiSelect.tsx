"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ChevronsUpDownIcon } from "lucide-react";

export function MultiSelect({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const labels = new Map(options.map((option) => [option.value, option.label]));

  function toggle(value: string) {
    const next = selected.includes(value)
      ? selected.filter((item) => item !== value)
      : [...selected, value];
    onChange(next);
  }

  return (
    <div className="space-y-2">
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="outline" className="w-full justify-between font-normal" aria-label={label}>
            <span className="truncate">{selected.length > 0 ? `${label} (${selected.length})` : label}</span>
            <ChevronsUpDownIcon className="size-4 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-64 p-0" align="start">
          <Command>
            <CommandInput placeholder={`Search ${label.toLowerCase()}`} />
            <CommandList>
              <CommandEmpty>No matches</CommandEmpty>
              <CommandGroup>
                {options.map((option) => {
                  const checked = selected.includes(option.value);
                  return (
                    <CommandItem key={option.value} value={option.label} onSelect={() => toggle(option.value)}>
                      <Checkbox checked={checked} tabIndex={-1} aria-hidden className="pointer-events-none" />
                      <span>{option.label}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((value) => (
            <Badge key={value} variant="secondary" className="gap-1">
              {labels.get(value) ?? value}
              <button type="button" className="text-muted-foreground" aria-label={`Remove ${labels.get(value) ?? value}`} onClick={() => toggle(value)}>
                ×
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

export function CheckGroup({
  name,
  options,
  selected,
  onToggle,
}: {
  name: string;
  options: { value: string; label: string }[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <div className="space-y-2.5">
      {options.map((option) => {
        const id = `${name}-${option.value}`;
        return (
          <div key={id} className="flex items-center gap-2.5">
            <Checkbox id={id} checked={selected.includes(option.value)} onCheckedChange={() => onToggle(option.value)} />
            <label htmlFor={id} className="text-sm font-normal">
              {option.label}
            </label>
          </div>
        );
      })}
    </div>
  );
}
