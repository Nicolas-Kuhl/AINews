import { useCallback, useEffect, useRef, useState } from "react";

const KEY = "ainews.readerWidth";
const MIN = 360;
const DEFAULT = 540;
// Leave room for the 240px sidebar + a usable list pane.
const maxWidth = () => Math.max(MIN, Math.min(900, window.innerWidth - 240 - 360));

function clamp(px: number): number {
  return Math.max(MIN, Math.min(maxWidth(), px));
}

/** Drag-to-resize state for the reader pane, persisted across sessions.
 *  Returns the current width and a pointer-down handler for the drag grip. */
export function useReaderWidth(): [number, (e: React.PointerEvent) => void] {
  const [width, setWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem(KEY));
    return saved >= MIN ? clamp(saved) : DEFAULT;
  });
  const dragging = useRef(false);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return;
      // Reader is anchored to the right edge: width grows as the pointer
      // moves left, so width = (viewport right edge) - pointer X.
      setWidth(clamp(window.innerWidth - e.clientX));
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      setWidth((w) => {
        localStorage.setItem(KEY, String(w));
        return w;
      });
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  return [width, onPointerDown];
}
