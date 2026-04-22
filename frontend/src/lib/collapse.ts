import { useCallback, useState } from "react";

const PREFIX = "ainews.dayCollapsed.";

type Stored = "collapsed" | "expanded" | null;

function read(date: string): Stored {
  try {
    const v = window.localStorage.getItem(PREFIX + date);
    if (v === "1") return "collapsed";
    if (v === "0") return "expanded";
    return null;
  } catch {
    return null;
  }
}

function write(date: string, collapsed: boolean) {
  try {
    window.localStorage.setItem(PREFIX + date, collapsed ? "1" : "0");
  } catch {
    /* no-op */
  }
}

export function useDayCollapse() {
  const [, bump] = useState(0);

  // The caller supplies the default (collapsed or not) so per-day defaults
  // can depend on position (e.g. first day expanded, older days collapsed).
  // A localStorage value always wins over the default.
  const isCollapsed = useCallback(
    (date: string, defaultCollapsed: boolean): boolean => {
      const stored = read(date);
      if (stored === "collapsed") return true;
      if (stored === "expanded") return false;
      return defaultCollapsed;
    },
    []
  );

  const toggle = useCallback((date: string, currentlyCollapsed: boolean) => {
    write(date, !currentlyCollapsed);
    bump((n) => n + 1);
  }, []);

  return { isCollapsed, toggle };
}
