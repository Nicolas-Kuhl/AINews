import { useEffect } from "react";
import {
  Streamlit,
  withStreamlitConnection,
  ComponentProps,
} from "streamlit-component-lib";
import { useTheme, Theme } from "./lib/theme";
import "./styles/triage.css";

type Story = {
  id: number;
  title: string;
  url: string;
  source: string;
  published: string | null;
  score: number;
  category: string | null;
  summary: string | null;
  score_reasoning: string | null;
  learning_objectives: string | null;
  lo_generated_with_opus: boolean;
  fetched_via: string | null;
  acknowledged: boolean;
  starred: boolean;
  group_id: number | null;
  related: Array<{ source: string; title: string; url: string }>;
  source_meta: {
    short: string;
    mark: string;
    hue: number;
    type: "Official" | "Press" | "Research" | "Platform" | "Newsletter";
  };
};

type ByDay = Array<{ date: string; label: string; stories: Story[] }>;

type Args = {
  by_day: ByDay;
  theme_default?: Theme;
};

function Reader({ args }: ComponentProps) {
  const { by_day, theme_default }: Args = args;
  const [theme, , toggleTheme] = useTheme(theme_default ?? "paper");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.body.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    Streamlit.setFrameHeight(window.innerHeight);
    const onResize = () => Streamlit.setFrameHeight(window.innerHeight);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const totalStories = (by_day ?? []).reduce(
    (acc, day) => acc + day.stories.length,
    0
  );
  const dayCount = (by_day ?? []).length;

  return (
    <div className="app" data-theme={theme}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">AI News</span>
          <button
            type="button"
            onClick={toggleTheme}
            aria-label="Toggle theme"
            title={theme === "paper" ? "Switch to terminal" : "Switch to paper"}
            style={{
              marginLeft: "auto",
              background: "none",
              border: "1px solid var(--rule)",
              borderRadius: 6,
              width: 32,
              height: 32,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--ink-3)",
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            {theme === "paper" ? "☾" : "☀"}
          </button>
        </div>
        <div className="sidebar-section-label">Sections</div>
        <nav className="nav" aria-label="Primary">
          <div className="nav-item is-active">Digest</div>
          <div className="nav-item">All stories</div>
          <div className="nav-item">Unread</div>
          <div className="nav-item">Starred</div>
          <div className="nav-item">Settings</div>
        </nav>
      </aside>
      <main
        style={{
          padding: "40px",
          color: "var(--ink)",
          background: "var(--bg)",
        }}
      >
        <div
          className="brief-label-col"
          style={{ marginBottom: 18 }}
        >
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
            Triage Console · Phase 1 preview
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
            {totalStories > 0
              ? `${totalStories} stories across ${dayCount} days`
              : "Component online — awaiting data"}
          </h1>
          <p
            style={{
              color: "var(--ink-3)",
              marginTop: 14,
              fontSize: 15,
              maxWidth: 640,
            }}
          >
            Theme toggle persists via <code>localStorage.ainews.theme</code>. Sidebar
            nav is a placeholder until M4 wires up filter state and view switching.
          </p>
        </div>
      </main>
    </div>
  );
}

export default withStreamlitConnection(Reader);
