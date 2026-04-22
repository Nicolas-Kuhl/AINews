import { useCallback, useState } from "react";

const PREFIX = "ainews.dayCollapsed.";

function read(date: string): boolean {
  try {
    return window.localStorage.getItem(PREFIX + date) === "1";
  } catch {
    return false;
  }
}

function write(date: string, collapsed: boolean) {
  try {
    if (collapsed) {
      window.localStorage.setItem(PREFIX + date, "1");
    } else {
      window.localStorage.removeItem(PREFIX + date);
    }
  } catch {
    /* no-op */
  }
}

export function useDayCollapse() {
  const [_, bump] = useState(0);

  const isCollapsed = useCallback((date: string) => read(date), []);
  const toggle = useCallback((date: string) => {
    write(date, !read(date));
    bump((n) => n + 1);
  }, []);

  return { isCollapsed, toggle };
}
