export type SectionKind = "intro" | "cold_open" | "segment" | "sign_off";

export type Bullet = {
  text: string;
  /** When this bullet slides in, relative to the section start. */
  revealAtSeconds: number;
};

export type Section = {
  kind: SectionKind;
  key: string;
  /** Path under renderer/public, e.g. "audio/2026-06-10/00-cold_open.mp3" */
  audio: string;
  durationSeconds: number;
  headline?: string;
  source?: string;
  /** 1-based segment number (segments only) */
  index?: number;
  bullets?: Bullet[];
};

export type EpisodeProps = {
  date: string;
  title: string;
  showName: string;
  tagline: string;
  siteUrl: string;
  segmentCount: number;
  sections: Section[];
};

/** Pause inserted after each section's audio ends. */
export const SECTION_GAP_SECONDS = 0.35;
export const FPS = 30;
