import { Day, MorningBrief as BriefType } from "../types";
import { relativeTime } from "../lib/format";
import { renderInlineMarkdown } from "../lib/markdown";

type Props = {
  brief: BriefType | null;
  days: Day[];
};

function computeStats(days: Day[]): { today: number; high: number; sources: number } {
  if (days.length === 0) return { today: 0, high: 0, sources: 0 };
  const today = days[0];
  const all = today.stories;
  const sources = new Set(all.map((s) => s.source));
  return {
    today: all.length,
    high: all.filter((s) => s.score >= 8).length,
    sources: sources.size,
  };
}

function prettyDate(iso: string): string {
  try {
    return new Date(iso + "T00:00:00Z").toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

export function MorningBriefHero({ brief, days }: Props) {
  if (!brief) return null;
  const stats = computeStats(days);
  return (
    <section className="brief">
      <div className="brief-head">
        <div className="brief-label-col">
          <div className="brief-kicker">
            Morning Brief · {prettyDate(brief.date)}
          </div>
          <h1 className="brief-heading">Morning Brief</h1>
          <div className="brief-generated">
            Auto-summary · {relativeTime(brief.generated_at)}
          </div>
        </div>
        <div className="brief-side">
          <div className="brief-stat">
            <div className="brief-stat-num">{stats.today}</div>
            <div className="brief-stat-label">stories today</div>
          </div>
          <div className="brief-stat">
            <div className="brief-stat-num">{stats.high}</div>
            <div className="brief-stat-label">scored 8+</div>
          </div>
          <div className="brief-stat">
            <div className="brief-stat-num">{stats.sources}</div>
            <div className="brief-stat-label">active sources</div>
          </div>
        </div>
      </div>
      <p className="brief-para">{renderInlineMarkdown(brief.paragraph)}</p>
    </section>
  );
}
