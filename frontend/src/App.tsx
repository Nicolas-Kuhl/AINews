import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Streamlit,
  withStreamlitConnection,
  ComponentProps,
} from "streamlit-component-lib";
import { Sidebar } from "./components/Sidebar";
import { DigestView } from "./components/DigestView";
import { Reader } from "./components/Reader";
import { MorningBriefHero } from "./components/MorningBrief";
import { useTheme } from "./lib/theme";
import {
  countStories,
  filterStories,
  starredCount,
  unreadCount,
} from "./lib/filter";
import { useKeyboardNav } from "./lib/keyboard";
import { Day, Filters, MorningBrief, Nav, Story, Theme } from "./types";
import "./styles/triage.css";
import "./styles/extras.css";

type Args = {
  by_day: Day[];
  morning_brief?: MorningBrief | null;
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

type Event =
  | { type: "ack"; id: number; value: boolean }
  | { type: "star"; id: number; value: boolean };

function ReaderApp({ args }: ComponentProps) {
  const { by_day, morning_brief, theme_default }: Args = args;
  const [theme, , toggleTheme] = useTheme(theme_default ?? "paper");
  const [nav, setNav] = useState<Nav>("digest");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // Optimistic local overrides that get cleared once Python echoes fresh data
  const [localAck, setLocalAck] = useState<Record<number, boolean>>({});
  const [localStar, setLocalStar] = useState<Record<number, boolean>>({});

  const seqRef = useRef(0);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.body.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    const parentHeight = (): number => {
      try {
        return window.top?.innerHeight ?? window.parent.innerHeight;
      } catch {
        return window.innerHeight;
      }
    };
    const sync = () => Streamlit.setFrameHeight(parentHeight());
    sync();
    // Sync on both iframe resize and parent resize — cover both directions.
    window.addEventListener("resize", sync);
    const parentWindow = window.parent;
    parentWindow?.addEventListener?.("resize", sync);
    // Also sync after a tick in case the parent layout hasn't settled.
    const t = window.setTimeout(sync, 200);
    return () => {
      window.removeEventListener("resize", sync);
      parentWindow?.removeEventListener?.("resize", sync);
      window.clearTimeout(t);
    };
  }, []);

  // Any time Python hands us a new by_day, drop local overrides — Python has
  // already applied the corresponding events to the DB.
  useEffect(() => {
    setLocalAck({});
    setLocalStar({});
  }, [by_day]);

  const sendEvent = useCallback((event: Event) => {
    seqRef.current += 1;
    Streamlit.setComponentValue({ seq: seqRef.current, events: [event] });
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
      const next = !story.acknowledged;
      setLocalAck((prev) => ({ ...prev, [story.id]: next }));
      sendEvent({ type: "ack", id: story.id, value: next });
    },
    [sendEvent]
  );

  const handleToggleStar = useCallback(
    (story: Story) => {
      const next = !story.starred;
      setLocalStar((prev) => ({ ...prev, [story.id]: next }));
      sendEvent({ type: "star", id: story.id, value: next });
    },
    [sendEvent]
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
          <>
            {nav === "digest" && (
              <MorningBriefHero brief={morning_brief ?? null} days={filteredDays} />
            )}
            <DigestView
              days={filteredDays}
              theme={theme}
              groupByDay={groupByDay}
              selectedId={selectedId}
              onSelect={handleSelect}
              onToggleAck={handleToggleAck}
            />
          </>
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
