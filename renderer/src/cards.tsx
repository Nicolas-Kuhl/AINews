import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "./theme";
import { EpisodeProps, Section } from "./types";

/** Fade the card in over the first few frames of its sequence. */
const useCardOpacity = () => {
  const frame = useCurrentFrame();
  return interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
};

const useEntrance = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame, fps, config: { damping: 200, stiffness: 80 } });
};

const Kicker: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      fontFamily: theme.mono,
      fontSize: 28,
      letterSpacing: "0.35em",
      textTransform: "uppercase",
      color: theme.accent,
    }}
  >
    {children}
  </div>
);

export const IntroCard: React.FC<EpisodeProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const entrance = spring({
    frame,
    fps,
    config: { damping: 200, stiffness: 60 },
  });

  // Equalizer-style bars pulsing under the show name while the sting plays
  const bars = Array.from({ length: 24 }, (_, i) => {
    const h = 18 + Math.abs(Math.sin(frame / 5 + i * 0.9)) * 46;
    return (
      <div
        key={i}
        style={{
          width: 12,
          height: h,
          borderRadius: 4,
          background:
            i % 3 === 0 ? theme.accent : i % 3 === 1 ? theme.accentCool : "#3F3F46",
        }}
      />
    );
  });

  return (
    <AbsoluteFill
      style={{ justifyContent: "center", alignItems: "center", gap: 56 }}
    >
      <div
        style={{
          fontFamily: theme.sans,
          fontWeight: 800,
          fontSize: 130,
          color: theme.text,
          transform: `scale(${0.8 + entrance * 0.2})`,
          opacity: entrance,
          letterSpacing: "-0.02em",
        }}
      >
        {props.showName}
      </div>
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "flex-end",
          height: 70,
          opacity: Math.min(1, frame / 12),
        }}
      >
        {bars}
      </div>
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 30,
          letterSpacing: "0.3em",
          textTransform: "uppercase",
          color: theme.textDim,
          opacity: entrance,
        }}
      >
        {props.date}
      </div>
    </AbsoluteFill>
  );
};

export const ColdOpenCard: React.FC<EpisodeProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const opacity = useCardOpacity();
  const entrance = useEntrance();
  const headlines = props.sections
    .filter((s) => s.kind === "segment")
    .map((s) => s.headline ?? "");
  // Stagger the rundown in over the first ~40% of the cold open
  const revealEvery = Math.max(10, Math.round(fps * 0.7));

  return (
    <AbsoluteFill style={{ opacity, padding: "100px 140px" }}>
      <Kicker>
        {props.showName} // {props.date}
      </Kicker>
      <div
        style={{
          marginTop: 36,
          fontFamily: theme.sans,
          fontWeight: 800,
          fontSize: 76,
          lineHeight: 1.08,
          color: theme.text,
          maxWidth: 1550,
          transform: `translateY(${(1 - entrance) * 50}px)`,
        }}
      >
        {props.title}
      </div>

      {/* Today's rundown — every headline in the episode */}
      <div
        style={{
          marginTop: 64,
          display: "flex",
          flexDirection: "column",
          gap: 30,
        }}
      >
        <div
          style={{
            fontFamily: theme.mono,
            fontSize: 26,
            letterSpacing: "0.3em",
            color: theme.accentCool,
          }}
        >
          COMING UP
        </div>
        {headlines.map((h, i) => {
          const t = frame - 20 - i * revealEvery;
          const pop = spring({
            frame: Math.max(0, t),
            fps,
            config: { damping: 200, stiffness: 130 },
          });
          const visible = t >= 0;
          return (
            <div
              key={h}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 24,
                opacity: visible ? pop : 0,
                transform: `translateX(${visible ? (1 - pop) * -40 : -40}px)`,
              }}
            >
              <span
                style={{
                  fontFamily: theme.mono,
                  fontSize: 28,
                  color: theme.accent,
                  width: 46,
                }}
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              <span
                style={{
                  fontFamily: theme.sans,
                  fontWeight: 600,
                  fontSize: 40,
                  color: theme.text,
                  maxWidth: 1350,
                }}
              >
                {h}
              </span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const BulletRow: React.FC<{ text: string; revealFrame: number }> = ({
  text,
  revealFrame,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - revealFrame;
  const pop = spring({
    frame: Math.max(0, t),
    fps,
    config: { damping: 200, stiffness: 120 },
  });
  const visible = t >= 0;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 28,
        opacity: visible ? pop : 0,
        transform: `translateX(${visible ? (1 - pop) * -50 : -50}px)`,
      }}
    >
      {/* CSS triangle — a font glyph here rendered as tofu on Lambda's
          Chromium, whose system fonts lack the character */}
      <span
        style={{
          display: "inline-block",
          marginTop: 18,
          width: 0,
          height: 0,
          borderTop: "14px solid transparent",
          borderBottom: "14px solid transparent",
          borderLeft: `22px solid ${theme.accent}`,
          flexShrink: 0,
        }}
      />
      <span
        style={{
          fontFamily: theme.sans,
          fontWeight: 600,
          fontSize: 44,
          lineHeight: 1.35,
          color: theme.text,
          maxWidth: 1250,
        }}
      >
        {text}
      </span>
    </div>
  );
};

export const SegmentCard: React.FC<{
  section: Section;
  episode: EpisodeProps;
}> = ({ section, episode }) => {
  const opacity = useCardOpacity();
  const entrance = useEntrance();
  const { fps } = useVideoConfig();
  const bullets = section.bullets ?? [];

  return (
    <AbsoluteFill style={{ opacity, padding: 120 }}>
      {/* header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: theme.mono,
          fontSize: 30,
          color: theme.textDim,
        }}
      >
        <span style={{ color: theme.accent, letterSpacing: "0.25em" }}>
          {episode.showName.toUpperCase()}
        </span>
        <span style={{ letterSpacing: "0.25em" }}>
          SEGMENT {String(section.index ?? 0).padStart(2, "0")}/
          {String(episode.segmentCount).padStart(2, "0")}
        </span>
      </div>

      {/* headline — top third, makes room for the slide bullets */}
      <div
        style={{
          marginTop: 90,
          fontFamily: theme.sans,
          fontWeight: 800,
          fontSize: 72,
          lineHeight: 1.1,
          color: theme.text,
          maxWidth: 1500,
          transform: `translateY(${(1 - entrance) * 60}px)`,
          borderLeft: `10px solid ${theme.accent}`,
          paddingLeft: 36,
        }}
      >
        {section.headline}
      </div>

      {/* slideshow bullets, revealed in sync with the narration */}
      <div
        style={{
          marginTop: 80,
          display: "flex",
          flexDirection: "column",
          gap: 42,
        }}
      >
        {bullets.map((b) => (
          <BulletRow
            key={b.text}
            text={b.text}
            revealFrame={Math.round(b.revealAtSeconds * fps)}
          />
        ))}
      </div>

      {/* footer */}
      <div
        style={{
          position: "absolute",
          bottom: 110,
          left: 120,
          right: 120,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div
          style={{
            fontFamily: theme.mono,
            fontSize: 28,
            color: theme.bg,
            background: theme.accent,
            padding: "10px 22px",
            borderRadius: 6,
            fontWeight: 700,
          }}
        >
          SOURCE: {(section.source ?? "").toUpperCase()}
        </div>
        <div
          style={{
            fontFamily: theme.mono,
            fontSize: 26,
            color: theme.textDim,
          }}
        >
          {episode.date}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const SignOffCard: React.FC<EpisodeProps> = (props) => {
  const opacity = useCardOpacity();
  const entrance = useEntrance();

  return (
    <AbsoluteFill
      style={{
        opacity,
        justifyContent: "center",
        alignItems: "center",
        gap: 40,
      }}
    >
      <div
        style={{
          fontFamily: theme.sans,
          fontWeight: 800,
          fontSize: 96,
          color: theme.text,
          transform: `scale(${0.9 + entrance * 0.1})`,
        }}
      >
        {props.showName}
      </div>
      <div
        style={{ fontFamily: theme.mono, fontSize: 34, color: theme.textDim }}
      >
        New episode tomorrow.
      </div>
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 30,
          color: theme.accentCool,
          letterSpacing: "0.15em",
        }}
      >
        {props.siteUrl}
      </div>
      <Mascot />
    </AbsoluteFill>
  );
};

/** The show's quality-control supervisor, peeking in from the corner. */
const Mascot: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // Slide up from the bottom-right corner shortly after the card starts
  const pop = spring({
    frame: Math.max(0, frame - 15),
    fps,
    config: { damping: 16, stiffness: 90 },
  });

  return (
    <div
      style={{
        position: "absolute",
        right: 70,
        bottom: 0,
        transform: `translateY(${(1 - pop) * 320}px) rotate(${(1 - pop) * 6}deg)`,
        transformOrigin: "bottom center",
      }}
    >
      <Img
        src={staticFile("branding/mascot.png")}
        style={{ height: 320, display: "block" }}
      />
    </div>
  );
};
