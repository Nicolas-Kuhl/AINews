import {
  AbsoluteFill,
  Audio,
  Series,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { ColdOpenCard, SegmentCard, SignOffCard } from "./cards";
import { Backdrop } from "./Backdrop";
import { theme } from "./theme";
import { EpisodeProps, SECTION_GAP_SECONDS } from "./types";

export const Episode: React.FC<EpisodeProps> = (props) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const progress = Math.min(1, frame / Math.max(1, durationInFrames));

  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      <Backdrop />
      <Series>
        {props.sections.map((section) => {
          const frames = Math.ceil(
            (section.durationSeconds + SECTION_GAP_SECONDS) * fps,
          );
          // Local renders bundle audio via staticFile; Lambda renders get
          // S3 presigned URLs (the function can't see the EC2 disk).
          const audioSrc = section.audio.startsWith("http")
            ? section.audio
            : section.audio
              ? staticFile(section.audio)
              : null;
          return (
            <Series.Sequence key={section.key} durationInFrames={frames}>
              {audioSrc ? <Audio src={audioSrc} /> : null}
              {section.kind === "cold_open" ? (
                <ColdOpenCard {...props} />
              ) : section.kind === "sign_off" ? (
                <SignOffCard {...props} />
              ) : (
                <SegmentCard section={section} episode={props} />
              )}
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
