import { Day, Filters, Nav, Story } from "../types";

const PRESET_HOURS: Record<Filters["preset"], number | null> = {
  today: 0, // special: today-only
  "24h": 24,
  "7d": 24 * 7,
  "30d": 24 * 30,
  all: null,
};

function withinPreset(story: Story, preset: Filters["preset"]): boolean {
  if (preset === "all") return true;
  if (!story.published) return false;
  const published = new Date(story.published).getTime();
  const now = Date.now();
  if (preset === "today") {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return published >= today.getTime();
  }
  const hours = PRESET_HOURS[preset];
  if (hours === null) return true;
  return now - published <= hours * 3600 * 1000;
}

function matchesSearch(story: Story, search: string): boolean {
  if (!search) return true;
  const q = search.toLowerCase();
  const haystack = [
    story.title,
    story.summary ?? "",
    story.source,
    story.category ?? "",
    story.source_meta.short,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

function navPredicate(story: Story, nav: Nav): boolean {
  switch (nav) {
    case "digest":
    case "all":
      return true;
    case "unread":
      return !story.acknowledged;
    case "starred":
      return story.starred;
    case "settings":
      return false;
  }
}

export function filterStories(
  byDay: Day[],
  filters: Filters,
  nav: Nav
): Day[] {
  return byDay
    .map((day) => ({
      ...day,
      stories: day.stories.filter(
        (s) =>
          s.score >= filters.scoreMin &&
          (filters.showAck || !s.acknowledged) &&
          withinPreset(s, filters.preset) &&
          matchesSearch(s, filters.search) &&
          navPredicate(s, nav)
      ),
    }))
    .filter((day) => day.stories.length > 0);
}

export function countStories(byDay: Day[]): number {
  return byDay.reduce((acc, d) => acc + d.stories.length, 0);
}

export function unreadCount(byDay: Day[]): number {
  return byDay.reduce(
    (acc, d) => acc + d.stories.filter((s) => !s.acknowledged).length,
    0
  );
}

export function starredCount(byDay: Day[]): number {
  return byDay.reduce(
    (acc, d) => acc + d.stories.filter((s) => s.starred).length,
    0
  );
}
