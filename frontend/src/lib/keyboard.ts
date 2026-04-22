import { useEffect } from "react";
import { Day } from "../types";

type Handlers = {
  days: Day[];
  selectedId: number | null;
  setSelectedId: (id: number | null) => void;
  onToggleAckCurrent: () => void;
};

function flatten(days: Day[]): number[] {
  return days.flatMap((d) => d.stories.map((s) => s.id));
}

export function useKeyboardNav({
  days,
  selectedId,
  setSelectedId,
  onToggleAckCurrent,
}: Handlers) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Skip when typing in an input/textarea
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }

      const ids = flatten(days);
      if (ids.length === 0) return;
      const idx = selectedId == null ? -1 : ids.indexOf(selectedId);

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = idx < 0 ? ids[0] : ids[Math.min(idx + 1, ids.length - 1)];
        setSelectedId(next);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (idx <= 0) return;
        setSelectedId(ids[idx - 1]);
      } else if (e.key === "Escape") {
        e.preventDefault();
        setSelectedId(null);
      } else if (e.key === "e" || e.key === "E") {
        if (selectedId != null) {
          e.preventDefault();
          onToggleAckCurrent();
        }
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [days, selectedId, setSelectedId, onToggleAckCurrent]);
}
