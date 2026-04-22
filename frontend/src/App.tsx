import { useEffect, useMemo, useState } from "react";
import {
  Streamlit,
  withStreamlitConnection,
  ComponentProps,
} from "streamlit-component-lib";
import { Sidebar } from "./components/Sidebar";
import { DigestView } from "./components/DigestView";
import { useTheme } from "./lib/theme";
import {
  countStories,
  filterStories,
  starredCount,
  unreadCount,
} from "./lib/filter";
import { Day, Filters, Nav, Story, Theme } from "./types";
import "./styles/triage.css";
import "./styles/extras.css";

type Args = {
  by_day: Day[];
  theme_default?: Theme;
};

const DEFAULT_FILTERS: Filters = {
  search: "",
  preset: "30d",
  scoreMin: 1,
  showAck: false,
};

function Reader({ args }: ComponentProps) {
  const { by_day, theme_default }: Args = args;
  const [theme, , toggleTheme] = useTheme(theme_default ?? "paper");
  const [nav, setNav] = useState<Nav>("digest");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.body.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    const sync = () => Streamlit.setFrameHeight(window.innerHeight);
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);

  const days: Day[] = by_day ?? [];
  const filteredDays = useMemo(
    () => filterStories(days, filters, nav),
    [days, filters, nav]
  );

  const counts = useMemo(
    () => ({
      all: countStories(days),
      unread: unreadCount(days),
      starred: starredCount(days),
    }),
    [days]
  );

  const handleSelect = (story: Story) => setSelectedId(story.id);
  const handleToggleAck = (_story: Story) => {
    // Wired end-to-end in M7
  };

  const groupByDay = nav === "digest";

  return (
    <div className="app is-three-pane" data-theme={theme}>
      <Sidebar
        nav={nav}
        setNav={setNav}
        filters={filters}
        setFilters={setFilters}
        counts={counts}
        theme={theme}
        toggleTheme={toggleTheme}
      />
      <main className="main-pane">
        {nav === "settings" ? (
          <div className="empty-msg">Settings view lives in the legacy dashboard for now.</div>
        ) : (
          <DigestView
            days={filteredDays}
            theme={theme}
            groupByDay={groupByDay}
            selectedId={selectedId}
            onSelect={handleSelect}
            onToggleAck={handleToggleAck}
          />
        )}
      </main>
      <aside className="reader-drawer">
        <div className="empty-msg">
          Select a story to read.
          <div
            style={{
              marginTop: 8,
              fontSize: 13,
              color: "var(--ink-4)",
            }}
          >
            Or press ↑ / ↓ to navigate.
          </div>
        </div>
      </aside>
    </div>
  );
}

export default withStreamlitConnection(Reader);
