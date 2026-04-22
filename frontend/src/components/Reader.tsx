import { Story, Theme } from "../types";
import {
  clipSentences,
  markMarginColor,
  relativeTime,
  scoreBand,
  sourceTypeClass,
} from "../lib/format";

type Props = {
  story: Story | null;
  theme: Theme;
  onClose: () => void;
  onToggleAck: (story: Story) => void;
  onToggleStar: (story: Story) => void;
  onGenerateLO: (story: Story) => void;
  generatingLO: boolean;
};

function verdict(score: number): string {
  if (score >= 9) return "Top of feed";
  if (score >= 7) return "High priority";
  return "Worth a skim";
}

function renderLearningObjectives(markdown: string) {
  const lines = markdown
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.startsWith("-"))
    .map((l) => l.replace(/^[-*]\s*/, ""));
  if (lines.length === 0) return null;
  return (
    <div className="reader-lo-wrap">
      <ol className="reader-lo-list">
        {lines.map((line, idx) => (
          <li key={idx}>{line}</li>
        ))}
      </ol>
    </div>
  );
}

export function Reader({
  story,
  theme,
  onClose,
  onToggleAck,
  onToggleStar,
  onGenerateLO,
  generatingLO,
}: Props) {
  if (!story) {
    return (
      <aside className="reader">
        <div className="reader-empty">
          Select a story to read.
          <div className="reader-empty-sub">Or press ↑ / ↓ to navigate.</div>
        </div>
      </aside>
    );
  }

  const band = scoreBand(story.score);
  return (
    <aside className="reader">
      <div className="reader-topbar">
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--ink-3)",
          }}
        >
          Reading pane
        </div>
        <div className="reader-topbar-actions">
          <button
            type="button"
            className={`icon-btn ${story.starred ? "primary" : ""}`}
            onClick={() => onToggleStar(story)}
            aria-pressed={story.starred}
          >
            {story.starred ? "★ Starred" : "☆ Star"}
          </button>
          <button
            type="button"
            className={`icon-btn ${story.acknowledged ? "" : "primary"}`}
            onClick={() => onToggleAck(story)}
          >
            {story.acknowledged ? "Acknowledged ✓" : "Mark read"}
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="Close reader"
          >
            ×
          </button>
        </div>
      </div>

      <div className="reader-body">
        <div className="reader-kicker">
          <div className={`reader-score ${band}`}>{story.score}</div>
          <div className="reader-score-meta">
            <div className="reader-score-label">Signal score</div>
            <div style={{ color: "var(--ink-2)", fontSize: 13 }}>
              {verdict(story.score)}
            </div>
          </div>
        </div>

        <h1 className="reader-title">{story.title}</h1>
        {(story.short_summary || story.summary) && (
          <div className="reader-dek">
            {story.short_summary || clipSentences(story.summary, 3)}
          </div>
        )}

        <a
          className="reader-byline reader-byline-link"
          href={story.url}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open original story from ${story.source_meta.short}`}
        >
          <div
            className="reader-byline-logo"
            style={{
              background: markMarginColor(story.source_meta.hue, theme),
              width: 32,
              height: 32,
              borderRadius: 8,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-ui)",
              fontSize: 13,
              fontWeight: 600,
              color: "var(--ink)",
            }}
          >
            {story.source_meta.mark}
          </div>
          <div className="reader-byline-text">
            <div className="reader-byline-source">
              {story.source_meta.short}
            </div>
            <div className="reader-byline-date">
              {relativeTime(story.published)}
              {story.fetched_via ? ` · via ${story.fetched_via}` : ""}
            </div>
          </div>
          <span
            className={`reader-byline-ext ${sourceTypeClass(story.source_meta.type)}`}
            style={{ marginLeft: "auto" }}
            aria-hidden="true"
          >
            ↗
          </span>
        </a>

        {story.summary && story.summary.length > 240 ? null : null}

        {story.summary && (
          <div className="reader-section">
            <div className="reader-section-label">Summary</div>
            <div className="reader-summary">{story.summary}</div>
          </div>
        )}

        {story.score_reasoning && (
          <div className="reader-section">
            <div className="reader-section-label">Why this score</div>
            <div className="reader-reasoning">{story.score_reasoning}</div>
          </div>
        )}

        <div className="reader-section">
          <div className="reader-section-label">
            Learning objectives
            {story.lo_generated_with_opus && (
              <span className="opus-badge" style={{ marginLeft: 8 }}>
                Opus
              </span>
            )}
          </div>
          {story.learning_objectives
            ? renderLearningObjectives(story.learning_objectives)
            : (
              <button
                type="button"
                className={`reader-gen-btn ${generatingLO ? "loading" : ""}`}
                disabled={generatingLO}
                onClick={() => onGenerateLO(story)}
              >
                {generatingLO ? "Generating with Opus…" : "Generate with Opus"}
              </button>
            )}
        </div>

        {story.related.length > 0 && (
          <div className="reader-section">
            <div className="reader-section-label">
              Also covered ({story.related.length})
            </div>
            <div className="reader-related">
              {story.related.map((r, idx) => (
                <a
                  key={idx}
                  className="reader-related-item"
                  href={r.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <span className="reader-related-source">{r.source}</span>
                  <span className="reader-related-title">{r.title}</span>
                  <span className="reader-related-ext">↗</span>
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
