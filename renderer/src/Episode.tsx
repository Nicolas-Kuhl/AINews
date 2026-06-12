import {
  AbsoluteFill,
  Audio,
  Series,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { ColdOpenCard, IntroCard, SegmentCard, SignOffCard } from "./cards";
import { Backdrop } from "./Backdrop";
import { theme } from "./theme";
import { EpisodeProps, gapAfterSeconds } from "./types";

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
