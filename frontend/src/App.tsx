import { useEffect, useState } from "react";
import {
  Streamlit,
  withStreamlitConnection,
  ComponentProps,
} from "streamlit-component-lib";

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
  theme_default?: "paper" | "terminal";
};

function Reader({ args }: ComponentProps) {
  const { by_day, theme_default }: Args = args;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    Streamlit.setFrameHeight(window.innerHeight);
    const onResize = () => Streamlit.setFrameHeight(window.innerHeight);
    window.addEventListener("resize", onResize);
    setReady(true);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const totalStories = (by_day ?? []).reduce(
    (acc, day) => acc + day.stories.length,
    0
  );

  return (
    <div
      data-theme={theme_default ?? "paper"}
      style={{
        fontFamily:
          "'Geist', -apple-system, 'Segoe UI', system-ui, sans-serif",
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#0A0A0A",
        background: "#FAFAFA",
        fontSize: "16px",
        letterSpacing: "-0.012em",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: "26px", fontWeight: 600, letterSpacing: "-0.035em" }}>
          AI News Reader — component online
        </div>
        <div style={{ color: "#71717A", marginTop: 8, fontFamily: "'Geist Mono', monospace", fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase" }}>
          {ready ? `Received ${totalStories} stories across ${(by_day ?? []).length} days` : "Initializing"}
        </div>
      </div>
    </div>
  );
}

export default withStreamlitConnection(Reader);
