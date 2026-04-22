import { useEffect, useMemo, useState } from "react";
import {
  Streamlit,
  withStreamlitConnection,
  ComponentProps,
} from "streamlit-component-lib";
import { Sidebar } from "./components/Sidebar";
import { useTheme } from "./lib/theme";
import {
  countStories,
  filterStories,
  starredCount,
  unreadCount,
} from "./lib/filter";
import { Day, Filters, Nav, Theme } from "./types";
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

  const days = by_day ?? [];
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

  const shownCount = countStories(filteredDays);

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
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--accent)",
            fontWeight: 600,
          }}
        >
          Triage Console · Phase 1 preview · {nav}
        </div>
        <h1
          style={{
            fontSize: 26,
            fontWeight: 600,
            letterSpacing: "-0.035em",
            margin: "6px 0 0",
            color: "var(--ink)",
            lineHeight: 1,
          }}
        >
          {nav === "settings"
            ? "Settings"
            : shownCount === 0
            ? "No stories match your filters"
            : `${shownCount} stories across ${filteredDays.length} days`}
        </h1>
        <p
          style={{
            color: "var(--ink-3)",
            marginTop: 14,
            fontSize: 15,
            maxWidth: 640,
          }}
        >
          Story rows land in M5. Selection, reader drawer, and keyboard nav in M6.
        </p>
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
