import { SourceType } from "../types";

export function scoreBand(score: number): "high" | "mid" | "low" {
  if (score >= 8) return "high";
  if (score >= 5) return "mid";
  return "low";
}

export function categorySlug(category: string | null): string {
  if (!category) return "";
  const c = category.toLowerCase();
  if (c.includes("release")) return "cat-releases";
  if (c.includes("research")) return "cat-research";
  if (c.includes("business")) return "cat-business";
  if (c.includes("dev") || c.includes("tool")) return "cat-devtools";
  return "";
}

export function categoryDisplay(category: string | null): string {
  if (!category) return "";
  if (/developer tools/i.test(category)) return "Dev Tools";
  return category;
}

export function sourceTypeClass(type: SourceType): string {
  return `type-${type.toLowerCase()}`;
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "";
  const diff = Date.now() - ts;
  if (diff < 0) return "soon";
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.round(days / 7);
  if (weeks < 5) return `${weeks}w ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export function absoluteTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hh = d.getUTCHours().toString().padStart(2, "0");
  const mm = d.getUTCMinutes().toString().padStart(2, "0");
  return `${hh}:${mm} UTC`;
}

export function markMarginColor(hue: number, theme: "paper" | "terminal"): string {
  return theme === "paper"
    ? `oklch(96% 0.04 ${hue})`
    : `oklch(28% 0.06 ${hue})`;
}

/**
 * Clip a summary to at most ``maxSentences`` sentences. Preserves the full
 * summary when shorter; the Reader drawer always shows the untrimmed text.
 */
export function clipSentences(text: string | null, maxSentences: number): string {
  if (!text) return "";
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  // Capture each sentence plus its trailing punctuation + whitespace.
  const parts = normalized.match(/[^.!?]+[.!?]+(\s|$)/g);
  if (!parts) return normalized;
  const kept = parts.slice(0, maxSentences).join("").trim();
  return kept || normalized;
}
