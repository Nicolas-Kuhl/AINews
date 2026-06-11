import { AbsoluteFill, useCurrentFrame } from "remotion";
import { theme } from "./theme";

/** Slowly drifting gradient blobs — keeps long narration sections alive
 *  without distracting from the text. Pure CSS, cheap to render. */
export const Backdrop: React.FC = () => {
  const frame = useCurrentFrame();
  const t = frame / 30;
  const x1 = Math.sin(t * 0.11) * 140;
  const y1 = Math.cos(t * 0.07) * 90;
  const x2 = Math.cos(t * 0.09) * 170;
  const y2 = Math.sin(t * 0.13) * 110;

  const blob = (
    color: string,
    size: number,
    left: string,
    top: string,
    dx: number,
    dy: number,
  ): React.CSSProperties => ({
    position: "absolute",
    width: size,
    height: size,
    left,
    top,
    transform: `translate(${dx}px, ${dy}px)`,
    background: `radial-gradient(circle, ${color} 0%, transparent 65%)`,
    opacity: 0.16,
    filter: "blur(40px)",
  });

  return (
    <AbsoluteFill>
      <div style={blob(theme.accent, 900, "-12%", "-25%", x1, y1)} />
      <div style={blob(theme.accentCool, 800, "62%", "45%", x2, y2)} />
      {/* faint scanline texture, echoes the dashboard's terminal look */}
      <AbsoluteFill
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(255,255,255,0.015) 0px, rgba(255,255,255,0.015) 1px, transparent 1px, transparent 4px)",
        }}
      />
    </AbsoluteFill>
  );
};
