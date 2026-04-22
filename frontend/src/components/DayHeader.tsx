import { Story } from "../types";
import { scoreBand } from "../lib/format";

type Props = {
  date: string;
  label: string;
  stories: Story[];
  collapsed: boolean;
  onToggle: () => void;
};

const COLOR_BY_BAND: Record<"high" | "mid" | "low", string> = {
  high: "var(--score-high)",
  mid: "var(--score-mid)",
  low: "var(--score-low)",
};

function barHeight(score: number): number {
  return 4 + Math.round((Math.max(0, Math.min(10, score)) / 10) * 14);
}

export function DayHeader({
  date,
  label,
  stories,
  collapsed,
  onToggle,
}: Props) {
  const highCount = stories.filter((s) => s.score >= 8).length;
  return (
    <button
      type="button"
      className="day-header"
      onClick={onToggle}
      aria-expanded={!collapsed}
      aria-controls={`day-${date}-body`}
    >
      <div className="day-header-left">
        <svg
          className={`day-chev ${collapsed ? "is-collapsed" : ""}`}
          viewBox="0 0 12 12"
          width="12"
          height="12"
          aria-hidden="true"
        >
          <path
            d="M3 4.5 L6 7.5 L9 4.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <div className="day-title">{label}</div>
      </div>
      <div className="day-meta">
        <div className="day-heatmap" aria-hidden="true">
          {stories.map((s, idx) => (
            <span
              key={`${date}-${idx}`}
              style={{
                display: "inline-block",
                width: 6,
                height: barHeight(s.score),
                background: COLOR_BY_BAND[scoreBand(s.score)],
                borderRadius: 1,
              }}
            />
          ))}
        </div>
        <div className="day-count">
          {stories.length} STOR{stories.length === 1 ? "Y" : "IES"}
          {highCount > 0 ? ` · ${highCount} SCORED 8+` : ""}
        </div>
      </div>
    </button>
  );
}
