import { Filters, Nav, Preset, SourceType, Theme } from "../types";

type Props = {
  nav: Nav;
  setNav: (n: Nav) => void;
  filters: Filters;
  setFilters: (f: Filters) => void;
  counts: { all: number; unread: number; starred: number };
  theme: Theme;
  toggleTheme: () => void;
};

const NAV_ITEMS: Array<{ key: Nav; label: string }> = [
  { key: "digest", label: "Digest" },
  { key: "all", label: "All stories" },
  { key: "unread", label: "Unread" },
  { key: "starred", label: "Starred" },
  { key: "settings", label: "Settings" },
];

const PRESETS: Array<{ key: Preset; label: string }> = [
  { key: "today", label: "Today" },
  { key: "24h", label: "Last 24h" },
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "all", label: "All time" },
];

const SCORE_MINS = [1, 5, 7, 8, 9];

const SOURCE_TYPES: SourceType[] = ["Official", "Newsletter", "Web Scrape"];

export function Sidebar({
  nav,
  setNav,
  filters,
  setFilters,
  counts,
  theme,
  toggleTheme,
}: Props) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">AI News</span>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label="Toggle theme"
          title={theme === "paper" ? "Switch to terminal" : "Switch to paper"}
          className="theme-toggle"
        >
          {theme === "paper" ? "☾" : "☀"}
        </button>
      </div>

      <div>
        <div className="sidebar-section-label">Sections</div>
        <nav className="nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => {
            const count =
              item.key === "unread"
                ? counts.unread
                : item.key === "starred"
                ? counts.starred
                : item.key === "all" || item.key === "digest"
                ? counts.all
                : null;
            // "Settings" leaves the component entirely — navigate the parent
            // to the Settings-standalone Streamlit route.
            if (item.key === "settings") {
              return (
                <a
                  key={item.key}
                  className="nav-item"
                  href="/?settings=1"
                  target="_top"
                  rel="noreferrer"
                >
                  <span>{item.label}</span>
                  <span className="nav-item-count">↗</span>
                </a>
              );
            }
            return (
              <button
                key={item.key}
                type="button"
                className={`nav-item ${nav === item.key ? "is-active" : ""}`}
                onClick={() => setNav(item.key)}
              >
                <span>{item.label}</span>
                {count !== null && (
                  <span className="nav-item-count">{count}</span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="filter-group">
        <div className="filter-label">Search</div>
        <input
          className="search-input"
          placeholder="Title, source, category…"
          value={filters.search}
          onChange={(e) =>
            setFilters({ ...filters, search: e.target.value })
          }
        />
      </div>

      <div className="filter-group">
        <div className="filter-label">Quick view</div>
        <div className="preset-group">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              className={`preset-btn ${filters.preset === p.key ? "is-active" : ""}`}
              onClick={() => setFilters({ ...filters, preset: p.key })}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="filter-group">
        <div className="filter-label">Min score</div>
        <div className="score-chips">
          {SCORE_MINS.map((n) => (
            <button
              key={n}
              type="button"
              className={`score-chip ${filters.scoreMin === n ? "is-active" : ""}`}
              onClick={() => setFilters({ ...filters, scoreMin: n })}
            >
              {n}+
            </button>
          ))}
        </div>
      </div>

      <div className="filter-group">
        <div className="filter-label">Source type</div>
        <div className="source-type-chips">
          {SOURCE_TYPES.map((t) => {
            const active = filters.sourceTypes.includes(t);
            return (
              <button
                key={t}
                type="button"
                className={`source-type-chip ${active ? "is-active" : ""}`}
                onClick={() => {
                  const next = active
                    ? filters.sourceTypes.filter((x) => x !== t)
                    : [...filters.sourceTypes, t];
                  setFilters({ ...filters, sourceTypes: next });
                }}
              >
                {t}
              </button>
            );
          })}
        </div>
      </div>

      <div className="toggle-row">
        <span>Show acknowledged</span>
        <button
          type="button"
          role="switch"
          aria-checked={filters.showAck}
          aria-label="Show acknowledged"
          className={`switch ${filters.showAck ? "is-on" : ""}`}
          onClick={() =>
            setFilters({ ...filters, showAck: !filters.showAck })
          }
        />
      </div>
    </aside>
  );
}
