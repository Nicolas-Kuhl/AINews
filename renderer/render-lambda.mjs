// Drives a distributed episode render on Remotion Lambda.
//
// Usage: node render-lambda.mjs <props.json> <output.mp4> <region> <site-name>
//
// Finds the deployed Remotion function and site, kicks off the render,
// polls progress, and downloads the finished MP4. Credentials come from
// the environment (EC2 instance role on the server).

import fs from "node:fs";
import {
  downloadMedia,
  getFunctions,
  getRenderProgress,
  getSites,
  renderMediaOnLambda,
} from "@remotion/lambda";

const [, , propsPath, outPath, region, siteName] = process.argv;
if (!propsPath || !outPath || !region || !siteName) {
  console.error("usage: node render-lambda.mjs <props.json> <out.mp4> <region> <site>");
  process.exit(2);
}

const inputProps = JSON.parse(fs.readFileSync(propsPath, "utf8"));

const functions = await getFunctions({ region, compatibleOnly: true });
if (functions.length === 0) {
  console.error(
    `No compatible Remotion Lambda function in ${region}. ` +
    "Deploy one with: npx remotion lambda functions deploy",
  );
  process.exit(1);
}
const functionName = functions[0].functionName;

const { sites } = await getSites({ region });
const site = sites.find((s) => s.id === siteName);
if (!site) {
  console.error(
    `Remotion site ${siteName} not found in ${region}. ` +
    `Deploy it with: npx remotion lambda sites create src/index.ts --site-name=${siteName}`,
  );
  process.exit(1);
}

console.log(`render: function=${functionName} site=${site.serveUrl}`);
const { renderId, bucketName } = await renderMediaOnLambda({
  region,
  functionName,
  serveUrl: site.serveUrl,
  composition: "Episode",
  inputProps,
  codec: "h264",
});

let lastPct = -1;
for (;;) {
  const progress = await getRenderProgress({
    renderId,
    bucketName,
    functionName,
    region,
  });
  if (progress.fatalErrorEncountered) {
    console.error("render failed:", progress.errors);
    process.exit(1);
  }
  if (progress.done) {
    break;
  }
  const pct = Math.round((progress.overallProgress ?? 0) * 100);
  if (pct !== lastPct) {
    console.log(`progress ${pct}%`);
    lastPct = pct;
  }
  await new Promise((r) => setTimeout(r, 3000));
}

const { outputPath, sizeInBytes } = await downloadMedia({
  region,
  bucketName,
  renderId,
  outPath,
});
console.log(`downloaded ${outputPath} (${(sizeInBytes / 1e6).toFixed(1)} MB)`);
