import { Composition, Still } from "remotion";
import { Cover } from "./Cover";
import { Episode } from "./Episode";
import { EpisodeProps, FPS, gapAfterSeconds } from "./types";

const SAMPLE_PROPS: EpisodeProps = {
  date: "2026-06-10",
  title: "When Your AI Starts Writing Its Own Resume",
  showName: "The Daily Prompt",
  tagline: "AI news. Daily. Slightly irreverent.",
  siteUrl: "ainews.eyrean.com",
  segmentCount: 2,
  sections: [
    {
      kind: "cold_open",
      key: "00-cold_open",
      audio: "",
      durationSeconds: 4,
    },
    {
      kind: "segment",
      key: "01-sample",
      audio: "",
      durationSeconds: 5,
      headline: "Anthropic Engineers Ship 8x More Code",
      source: "Futuretools.io",
      index: 1,
    },
    {
      kind: "segment",
      key: "02-sample",
      audio: "",
      durationSeconds: 5,
      headline: "China's $295 Billion Plan to Ditch Nvidia",
      source: "The Rundown AI",
      index: 2,
    },
    {
      kind: "sign_off",
      key: "03-sign_off",
      audio: "",
      durationSeconds: 4,
    },
  ],
};

export const Root: React.FC = () => {
  return (
    <>
    <Still id="Cover" component={Cover} width={3000} height={3000} />
    <Composition
      id="Episode"
      component={Episode}
      width={1920}
      height={1080}
      fps={FPS}
      defaultProps={SAMPLE_PROPS}
      calculateMetadata={({ props }) => {
        const totalSeconds = props.sections.reduce(
          (acc, s) => acc + s.durationSeconds + gapAfterSeconds(s.kind),
          0,
        );
        return {
          durationInFrames: Math.max(1, Math.ceil(totalSeconds * FPS)),
        };
      }}
    />
    </>
  );
};
