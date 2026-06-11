import {
  AbsoluteFill,
  interpolate,
  spring,
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

export const ColdOpenCard: React.FC<EpisodeProps> = (props) => {
  const opacity = useCardOpacity();
  const entrance = useEntrance();

  return (
    <AbsoluteFill
      style={{
        opacity,
        padding: 140,
        justifyContent: "center",
        gap: 48,
      }}
    >
      <Kicker>
        {props.showName} // {props.date}
      </Kicker>
      <div
        style={{
          fontFamily: theme.sans,
          fontWeight: 800,
          fontSize: 110,
          lineHeight: 1.05,
          color: theme.text,
          maxWidth: 1500,
          transform: `translateY(${(1 - entrance) * 60}px)`,
        }}
      >
        {props.title}
      </div>
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 34,
          color: theme.textDim,
        }}
      >
        {props.tagline}
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
      <span
        style={{
          color: theme.accent,
          fontFamily: theme.mono,
          fontSize: 38,
          lineHeight: 1.35,
        }}
      >
        ▸
      </span>
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
    </AbsoluteFill>
  );
};
