import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadJetBrainsMono } from "@remotion/google-fonts/JetBrainsMono";

// Load real webfonts so local and Lambda renders are pixel-identical —
// Lambda's Chromium has a different (sparser) system font set.
const inter = loadInter();
const jbMono = loadJetBrainsMono();

export const theme = {
  bg: "#0B0D12",
  bgPanel: "rgba(255, 255, 255, 0.04)",
  text: "#F4F4F5",
  textDim: "#9CA3AF",
  accent: "#F59E0B",
  accentCool: "#22D3EE",
  mono: `${jbMono.fontFamily}, 'Courier New', monospace`,
  sans: `${inter.fontFamily}, 'Helvetica Neue', Arial, sans-serif`,
};
