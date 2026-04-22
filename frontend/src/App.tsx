import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Streamlit,
  withStreamlitConnection,
  ComponentProps,
} from "streamlit-component-lib";
import { Sidebar } from "./components/Sidebar";
import { DigestView } from "./components/DigestView";
import { Reader } from "./components/Reader";
import { useTheme } from "./lib/theme";
import {
  countStories,
  filterStories,
  starredCount,
  unreadCount,
} from "./lib/filter";
import { useKeyboardNav } from "./lib/keyboard";
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

function findStory(days: Day[], id: number | null): Story | null {
  if (id == null) return null;
  for (const day of days) {
    for (const story of day.stories) {
      if (story.id === id) return story;
    }
  }
  return null;
}

function ReaderApp({ args }: ComponentProps) {
  const { by_day, theme_default }: Args = args;
  const [theme, , toggleTheme] = useTheme(theme_default ?? "paper");
  const [nav, setNav] = useState<Nav>("digest");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // Optimistic local overrides until M7 round-trips these to Python
  const [localAck, setLocalAck] = useState<Record<number, boolean>>({});
  const [localStar, setLocalStar] = useState<Record<number, boolean>>({});

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

  const days: Day[] = useMemo(() => {
    const incoming = by_day ?? [];
    if (
      Object.keys(localAck).length === 0 &&
      Object.keys(localStar).length === 0
    ) {
      return incoming;
    }
    return incoming.map((d) => ({
      ...d,
      stories: d.stories.map((s) => ({
        ...s,
        acknowledged:
          s.id in localAck ? localAck[s.id] : s.acknowledged,
        starred: s.id in localStar ? localStar[s.id] : s.starred,
      })),
    }));
  }, [by_day, localAck, localStar]);

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
  const handleCloseReader = () => setSelectedId(null);

  const handleToggleAck = useCallback(
    (story: Story) => {
      setLocalAck((prev) => ({ ...prev, [story.id]: !story.acknowledged }));
      // M7 will also Streamlit.setComponentValue(...) here
    },
    []
  );

  const handleToggleStar = useCallback(
    (story: Story) => {
      setLocalStar((prev) => ({ ...prev, [story.id]: !story.starred }));
    },
    []
  );

  const selectedStory = findStory(days, selectedId);

  const handleToggleAckCurrent = useCallback(() => {
    if (selectedStory) handleToggleAck(selectedStory);
  }, [selectedStory, handleToggleAck]);

  useKeyboardNav({
    days: filteredDays,
    selectedId,
    setSelectedId,
    onToggleAckCurrent: handleToggleAckCurrent,
  });

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
          <div className="empty-msg">
            Settings view lives in the legacy dashboard for now.
          </div>
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
      <Reader
        story={selectedStory}
        theme={theme}
        onClose={handleCloseReader}
        onToggleAck={handleToggleAck}
        onToggleStar={handleToggleStar}
      />
    </div>
  );
}

export default withStreamlitConnection(ReaderApp);
