export type SourceType =
  | "Official"
  | "Press"
  | "Research"
  | "Platform"
  | "Newsletter";

export type SourceMeta = {
  short: string;
  mark: string;
  hue: number;
  type: SourceType;
};

export type RelatedLink = {
  source: string;
  title: string;
  url: string;
};

export type Story = {
  id: number;
  title: string;
  url: string;
  source: string;
  published: string | null;
  score: number;
  category: string | null;
  summary: string | null;
  score_reasoning: string | null;
  learning_objectives: string | null;
  lo_generated_with_opus: boolean;
  fetched_via: string | null;
  acknowledged: boolean;
  starred: boolean;
  group_id: number | null;
  related: RelatedLink[];
  source_meta: SourceMeta;
};

export type Day = {
  date: string;
  label: string;
  brief?: string | null;
  stories: Story[];
};

export type MorningBrief = {
  date: string;
  generated_at: string;
  paragraph: string;
  stats_json?: string | null;
};

export type Nav = "digest" | "all" | "unread" | "starred" | "settings";

export type Preset = "today" | "24h" | "7d" | "30d" | "all";

export type Filters = {
  search: string;
  preset: Preset;
  scoreMin: number;
  showAck: boolean;
};

export type Theme = "paper" | "terminal";
