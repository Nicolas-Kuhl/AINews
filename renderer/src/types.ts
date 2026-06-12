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

export const FPS = 30;

/** Silent pause inserted after a section's audio ends, before the next one.
 *  A deliberate beat between spoken segments signals "new story"; the intro
 *  sting flows into the cold open with only a short breath. */
export const gapAfterSeconds = (kind: SectionKind): number => {
  switch (kind) {
    case "intro":
      return 0.25; // sting → cold open, keep it tight
    case "segment":
    case "cold_open":
      return 0.8; // the clear inter-segment pause
    case "sign_off":
    default:
      return 0.4;
  }
};
