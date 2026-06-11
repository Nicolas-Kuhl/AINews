import { Config } from "@remotion/cli/config";

// The render host (c7i-flex.large) has 2 vCPUs and 3.7 GB RAM — keep
// Chromium's appetite modest. Nightly batch renders don't need speed.
Config.setConcurrency(1);
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
