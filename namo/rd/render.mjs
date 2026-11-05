// Render a NAMO explainer (or any composition in an entry) to mp4 with rendiv on CPU.
//
//   node render.mjs --out film.mp4 [--beats beats/gita-1-1.json] [--seconds 75] [--ratio 16:9]
//                   [--size 1920x1080] [--fps 30] [--entry src/index.tsx] [--comp Explainer]
//                   [--concurrency N] [--vo-only 1]
//
// With --beats, beat times are scaled to --seconds (default: the beats file's own length) and
// the narration lines are written next to the film as <film>.vo.json:
//   [{id, t, end, text, lang}]   (seconds in the output film; same shape as engine VO)
// --vo-only 1 writes that file and stops (engine voices the film before rendering pictures).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { bundle } from '@rendiv/bundler';
import { renderMedia, selectComposition, closeBrowser } from '@rendiv/renderer';

const SIZE_FOR_RATIO = { '16:9': [1920, 1080], '9:16': [1080, 1920], '1:1': [1080, 1080] }; // = engine.SIZE_FOR_RATIO

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) =>
  v.startsWith('--') ? [...a, [v.slice(2), all[i + 1]]] : a, []));
if (!args.out) { console.error('--out is required'); process.exit(2); }
const out = path.resolve(args.out);
const here = path.dirname(fileURLToPath(import.meta.url));
process.chdir(here); // the bundler roots vite at cwd

const fps = Number(args.fps ?? 30);
const ratio = args.ratio ?? '16:9';
if (!args.size && !SIZE_FOR_RATIO[ratio]) { console.error(`unknown ratio ${ratio}`); process.exit(2); }
const [width, height] = args.size ? args.size.split('x').map(Number) : SIZE_FOR_RATIO[ratio];

let props = {};
let seconds = null;
if (args.beats) {
  const doc = JSON.parse(fs.readFileSync(path.resolve(args.beats), 'utf8'));
  const native = doc.beats.reduce((m, b) => Math.max(m, b.t + b.dur), 0);
  seconds = Number(args.seconds ?? native);
  const k = seconds / native;
  const beats = doc.beats.map((b) => ({ ...b, t: b.t * k, dur: b.dur * k }));
  props = { doc: { ...doc, beats }, width, height, fps, seconds };
  const vo = beats.filter((b) => b.vo).map((b) => ({
    id: b.id, t: +b.t.toFixed(3), end: +(b.t + b.dur).toFixed(3), text: b.vo, lang: doc.lang ?? 'hi',
  }));
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out.replace(/\.mp4$/i, '') + '.vo.json', JSON.stringify(vo, null, 1));
  if (args['vo-only']) process.exit(0);
}

const t0 = Date.now();
// absolute + forward slashes: rendiv's bundler pastes the path into an import string (backslashes break on Windows)
const entry = path.resolve(args.entry ?? 'src/index.tsx').replaceAll('\\', '/');
const serveUrl = await bundle({ entryPoint: entry, outDir: path.join(os.tmpdir(), `rd-bundle-${process.pid}`) });
const comp = await selectComposition(serveUrl, args.comp ?? 'Explainer', props);
const composition = seconds == null ? comp : { ...comp, width, height, fps, durationInFrames: Math.round(seconds * fps) };
const t1 = Date.now();
let last = -1;
await renderMedia({
  composition, serveUrl, codec: 'mp4', outputLocation: out, inputProps: props,
  concurrency: Number(args.concurrency ?? Math.max(1, os.cpus().length - 1)),
  imageFormat: 'jpeg', jpegQuality: 92, crf: 20, encodingPreset: 'medium',
  onProgress: ({ progress }) => {
    const p = Math.floor(progress * 10);
    if (p !== last) { last = p; process.stdout.write(`${p * 10}% `); }
  },
});
await closeBrowser();
fs.rmSync(serveUrl, { recursive: true, force: true });
const t2 = Date.now();
const vidSec = composition.durationInFrames / composition.fps;
console.log(`\n${out}\n${composition.width}x${composition.height} ${composition.durationInFrames}f@${composition.fps} ` +
  `bundle ${((t1 - t0) / 1000).toFixed(1)}s render ${((t2 - t1) / 1000).toFixed(1)}s ` +
  `= ${((t2 - t1) / 1000 / vidSec).toFixed(2)} s compute per s video`);
