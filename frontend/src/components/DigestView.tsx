import { Day, Story, Theme } from "../types";
import { DayHeader } from "./DayHeader";
import { StoryRow } from "./StoryRow";
import { useDayCollapse } from "../lib/collapse";
import { renderInlineMarkdown } from "../lib/markdown";

type Props = {
  days: Day[];
  theme: Theme;
  groupByDay: boolean;
  selectedId: number | null;
  onSelect: (story: Story) => void;
  onToggleAck: (story: Story) => void;
};

export function DigestView({
  days,
  theme,
  groupByDay,
  selectedId,
  onSelect,
  onToggleAck,
}: Props) {
  const { isCollapsed, toggle } = useDayCollapse();

  if (days.length === 0) {
    return <div className="empty-msg">No stories match your filters.</div>;
  }

  const flat = (): Story[] => days.flatMap((d) => d.stories);

  if (!groupByDay) {
    return (
      <div>
        {flat().map((story) => (
          <StoryRow
            key={story.id}
            story={story}
            theme={theme}
            isSelected={story.id === selectedId}
            onSelect={onSelect}
            onToggleAck={onToggleAck}
          />
        ))}
      </div>
    );
  }

  return (
    <div>
      {days.map((day) => {
        const collapsed = isCollapsed(day.date);
        const highCount = day.stories.filter((s) => s.score >= 8).length;
        return (
          <section key={day.date}>
            <DayHeader
              date={day.date}
              label={day.label}
              stories={day.stories}
              collapsed={collapsed}
              onToggle={() => toggle(day.date)}
            />
            {!collapsed && day.brief && (
              <div className="day-summary" id={`day-${day.date}-brief`}>
                <div className="day-summary-head">
                  <span className="day-summary-kicker">Day Brief</span>
                  <span className="day-summary-meta">
                    {day.stories.length} stories
                    {highCount > 0 ? ` · ${highCount} scored 8+` : ""}
                  </span>
                </div>
                <p className="day-summary-text">
                  {renderInlineMarkdown(day.brief)}
                </p>
              </div>
            )}
            {!collapsed && (
              <div id={`day-${day.date}-body`}>
                {day.stories.map((story) => (
                  <StoryRow
                    key={story.id}
                    story={story}
                    theme={theme}
                    isSelected={story.id === selectedId}
                    onSelect={onSelect}
                    onToggleAck={onToggleAck}
                  />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
