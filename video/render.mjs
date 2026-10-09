// 渲染宣传片和官网用图。用法：
//   node render.mjs frames film-en 120,400,900   看几帧（存到 out/frames/）
//   node render.mjs film                          两种语言的宣传片（无声，配乐另外合进去）
//   node render.mjs shots [名字]                  官网和 README 用的截图（可以只渲染其中几张）
import { bundle } from "@remotion/bundler";
import { getCompositions, renderMedia, renderStill, selectComposition } from "@remotion/renderer";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, "out");
const [cmd, ...args] = process.argv.slice(2);

const serveUrl = await bundle({ entryPoint: path.join(here, "src", "index.ts"), onProgress: () => {} });
const comp = (id) => selectComposition({ serveUrl, id, inputProps: {} });

if (cmd === "frames") {
  const [id, list] = args;
  const composition = await comp(id);
  mkdirSync(path.join(out, "frames"), { recursive: true });
  for (const frame of list.split(",").map(Number)) {
    const output = path.join(out, "frames", `${id}-${frame}.png`);
    await renderStill({ composition, serveUrl, output, frame, imageFormat: "png" });
    console.log(output);
  }
} else if (cmd === "film") {
  for (const id of args.length ? args : ["film-en", "film-zh"]) {
    const composition = await comp(id);
    const output = path.join(out, `${id}.mp4`);
    let last = -1;
    await renderMedia({
      composition,
      serveUrl,
      codec: "h264",
      crf: 16,
      imageFormat: "png",
      pixelFormat: "yuv420p",
      outputLocation: output,
      concurrency: 8,
      muted: true,
      onProgress: ({ progress }) => {
        const p = Math.floor(progress * 10);
        if (p !== last) console.log(`${id} ${p * 10}%`), (last = p);
      },
    });
    console.log(output);
  }
} else if (cmd === "shots") {
  const all = await getCompositions(serveUrl);
  mkdirSync(path.join(out, "shots"), { recursive: true });
  const only = args[0]; // 可以只渲染名字里带这个词的，比如 node render.mjs shots see
  for (const composition of all.filter((c) => /^(shot|og)-/.test(c.id) && (!only || c.id.includes(only)))) {
    const id = composition.id;
    const output = path.join(out, "shots", `${id}.png`);
    await renderStill({ composition, serveUrl, output, frame: 0, imageFormat: "png" });
    console.log(output);
  }
} else {
  console.error("用法：node render.mjs frames <id> <帧,帧> | film [id…] | shots");
  process.exit(2);
}
