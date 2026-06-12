import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Series,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { ColdOpenCard, IntroCard, SegmentCard, SignOffCard } from "./cards";
import { Backdrop } from "./Backdrop";
import { theme } from "./theme";
import { EpisodeProps, gapAfterSeconds } from "./types";

/** SVG chroma-key filter, applied to the avatar video. HeyGen's green is a
 *  uniform synthetic color, so a linear key + hard alpha threshold cleans it
 *  out reliably (no per-pixel JS, renders in headless Chromium). The despill
 *  pass knocks the green channel down on the remaining edges. */
const CHROMA_FILTER_ID = "avatar-chroma";
const ChromaKeyDefs: React.FC = () => (
  <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
    <defs>
      <filter id={CHROMA_FILTER_ID} colorInterpolationFilters="sRGB">
        {/* alpha = R - G + B + 1  → ~0 for green, clamps to 1 elsewhere */}
        <feColorMatrix
          type="matrix"
          values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  1 -1 1 0 1"
          result="keyed"
        />
        {/* hard cutoff so partial-green edges resolve to in/out */}
        <feComponentTransfer in="keyed" result="masked">
          <feFuncA type="discrete" tableValues="0 0 0 0 1 1 1 1 1 1" />
        </feComponentTransfer>
        {/* despill: pull green toward the red/blue average where it spiked */}
        <feColorMatrix
          in="masked"
          type="matrix"
          values="1 0 0 0 0  0.5 0.3 0.2 0 0  0 0 1 0 0  0 0 0 1 0"
        />
      </filter>
    </defs>
  </svg>
);

/** Chroma-keyed talking head, lower-right. The source is a green-screen clip
 *  whose green we remove at render time; its own audio is muted (Sophia plays
 *  on the main track). Springs up from the corner as the segment starts. */
const AvatarOverlay: React.FC<{ src: string }> = ({ src }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rise = spring({ frame, fps, config: { damping: 18, stiffness: 90 } });
  return (
    <div
      style={{
        position: "absolute",
        right: 56,
        bottom: 26,
        width: 460,
        height: 460,
        transform: `translateY(${(1 - rise) * 200}px)`,
        opacity: Math.min(1, frame / 8),
        filter: "drop-shadow(0 18px 40px rgba(0,0,0,0.55))",
      }}
    >
      <OffthreadVideo
        src={src}
        muted
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          filter: `url(#${CHROMA_FILTER_ID})`,
        }}
      />
    </div>
  );
};

export const Episode: React.FC<EpisodeProps> = (props) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const progress = Math.min(1, frame / Math.max(1, durationInFrames));

  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      <ChromaKeyDefs />
      <Backdrop />
      <Series>
        {props.sections.map((section) => {
          const frames = Math.ceil(
            (section.durationSeconds + gapAfterSeconds(section.kind)) * fps,
          );
          // Local renders bundle audio via staticFile; Lambda renders get
          // S3 presigned URLs (the function can't see the EC2 disk).
          const audioSrc = section.audio.startsWith("http")
            ? section.audio
            : section.audio
              ? staticFile(section.audio)
              : null;
          // The generated sting is mastered hot relative to the voiceover
          const volume = section.kind === "intro" ? 0.35 : 1;
          const avatarSrc = section.avatar
            ? section.avatar.startsWith("http")
              ? section.avatar
              : staticFile(section.avatar)
            : null;
          return (
            <Series.Sequence key={section.key} durationInFrames={frames}>
              {audioSrc ? <Audio src={audioSrc} volume={volume} /> : null}
              {section.kind === "intro" ? (
                <IntroCard {...props} />
              ) : section.kind === "cold_open" ? (
                <ColdOpenCard {...props} />
              ) : section.kind === "sign_off" ? (
                <SignOffCard {...props} />
              ) : (
                <SegmentCard section={section} episode={props} />
              )}
              {avatarSrc ? <AvatarOverlay src={avatarSrc} /> : null}
            </Series.Sequence>
          );
        })}
      </Series>
      {/* Whole-episode progress bar */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          height: 8,
          width: `${progress * 100}%`,
          background: `linear-gradient(90deg, ${theme.accent}, ${theme.accentCool})`,
        }}
      />
    </AbsoluteFill>
  );
};
