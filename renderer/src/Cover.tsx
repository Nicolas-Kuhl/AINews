import { AbsoluteFill, Img, staticFile } from "remotion";
import { theme } from "./theme";

/** Square podcast cover art (rendered once as a still, 3000x3000).
 *
 * Apple Podcasts requires 1400-3000px square RGB artwork. Type must stay
 * readable at thumbnail size (~60px), so: big wordmark, minimal detail,
 * the mascot anchoring the corner.
 */
export const Cover: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      {/* static gradient accents (no animation — it's a still) */}
      <div
        style={{
          position: "absolute",
          width: 2400,
          height: 2400,
          left: "-25%",
          top: "-30%",
          background: `radial-gradient(circle, ${theme.accent} 0%, transparent 62%)`,
          opacity: 0.22,
          filter: "blur(80px)",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 2000,
          height: 2000,
          left: "55%",
          top: "55%",
          background: `radial-gradient(circle, ${theme.accentCool} 0%, transparent 62%)`,
          opacity: 0.20,
          filter: "blur(80px)",
        }}
      />
      {/* scanline texture, matching the episodes */}
      <AbsoluteFill
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(255,255,255,0.02) 0px, rgba(255,255,255,0.02) 3px, transparent 3px, transparent 12px)",
        }}
      />

      <AbsoluteFill style={{ padding: 220, justifyContent: "center" }}>
        <div
          style={{
            fontFamily: theme.mono,
            fontSize: 92,
            letterSpacing: "0.32em",
            textTransform: "uppercase",
            color: theme.accent,
            marginBottom: 70,
          }}
        >
          AI NEWS // DAILY
        </div>
        <div
          style={{
            fontFamily: theme.sans,
            fontWeight: 800,
            fontSize: 360,
            lineHeight: 1.02,
            color: theme.text,
            letterSpacing: "-0.02em",
          }}
        >
          The
          <br />
          Daily
          <br />
          Prompt
        </div>
      </AbsoluteFill>

      {/* the supervisor */}
      <Img
        src={staticFile("branding/mascot.png")}
        style={{
          position: "absolute",
          right: 90,
          bottom: 0,
          height: 1150,
        }}
      />

      {/* progress-bar motif along the bottom edge */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: 36,
          background: `linear-gradient(90deg, ${theme.accent}, ${theme.accentCool})`,
        }}
      />
    </AbsoluteFill>
  );
};
