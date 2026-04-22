import { Story, Theme } from "../types";
import {
  absoluteTime,
  categoryDisplay,
  categorySlug,
  clipSentences,
  markMarginColor,
  relativeTime,
  scoreBand,
  sourceTypeClass,
} from "../lib/format";

type Props = {
  story: Story;
  theme: Theme;
  isSelected: boolean;
  onSelect: (story: Story) => void;
  onToggleAck: (story: Story) => void;
};

export function StoryRow({
  story,
  theme,
  isSelected,
  onSelect,
  onToggleAck,
}: Props) {
  const band = scoreBand(story.score);
  const catClass = categorySlug(story.category);
  const relatedCount = story.related.length;

  return (
    <div
      className={`row ${isSelected ? "is-selected" : ""} ${
        story.acknowledged ? "is-ack" : ""
      }`}
      onClick={() => onSelect(story)}
    >
      <div className="row-score-col">
        <div className={`score-num ${band}`}>{story.score}</div>
        <div className="score-label">Score</div>
      </div>

      <div className="row-source-card">
        <div
          className="row-source-mark"
          style={{ background: markMarginColor(story.source_meta.hue, theme) }}
        >
          {story.source_meta.mark}
        </div>
        <div className="row-source-meta">
          <div className="row-source-name">{story.source_meta.short}</div>
          <div
            className={`row-source-type ${sourceTypeClass(story.source_meta.type)}`}
          >
            {story.source_meta.type}
          </div>
        </div>
      </div>

      <div className="row-body">
        <div className="row-kicker">
          {story.category && (
            <span className={`row-cat ${catClass}`}>
              {categoryDisplay(story.category)}
            </span>
          )}
          <span className="row-dot">·</span>
          <span>{absoluteTime(story.published)}</span>
          {relatedCount > 0 && (
            <>
              <span className="row-dot">·</span>
              <span className="row-related">
                +<b>{relatedCount}</b> related
              </span>
            </>
          )}
        </div>
        <div className="row-title">{story.title}</div>
        {story.summary && (
          <div className="row-dek">{clipSentences(story.summary, 3)}</div>
        )}
      </div>

      <div className="row-published">
        {relativeTime(story.published)}
        <span className="row-published-time">
          {absoluteTime(story.published)}
        </span>
      </div>

      <div className="row-ack">
        <button
          type="button"
          className="ack-btn"
          aria-label={story.acknowledged ? "Acknowledged" : "Mark read"}
          onClick={(e) => {
            e.stopPropagation();
            onToggleAck(story);
          }}
        >
          ✓
        </button>
      </div>
    </div>
  );
}
