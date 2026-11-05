// NAMO Gita 1.1 — page entry. Contract: window.READY, window.render(t), window.DUR, window.EV, window.VO.
// Applies the brief: ?seconds= stretches the authored 60 s timeline linearly (the whole story always
// plays), ?ratio= sets the frame; the authored 1920x1080 picture is cover-cropped around the shot's subject.
import { makeComp, layerSet } from '/styles/ink-wash/demo/comp.js';
import { DUR as AUTHORED, VO } from './story.js';
import { clamp } from '/core/lib.js';

const q = new URLSearchParams(location.search);
const META = await (await fetch('./scene.json')).json();       // limits live in scene.json, not here
const AW = 1920, AH = 1080;                                    // the authored picture
const SIZE = { '16:9': [1920, 1080], '9:16': [1080, 1920], '1:1': [1080, 1080] };   // = engine.py SIZE_FOR_RATIO
const [MIN_S, MAX_S] = META.seconds_range;
const seconds = q.has('seconds') ? Number(q.get('seconds')) : AUTHORED;
const ratio = q.get('ratio') || META.ratio;
// Refuse what this scene cannot honour: an error here is a pageerror, so the render fails loudly.
if (!(seconds >= MIN_S && seconds <= MAX_S))
  throw new Error(`gita-ep01: seconds=${q.get('seconds')} is outside ${MIN_S}..${MAX_S}`);
if (!META.ratios.includes(ratio)) throw new Error(`gita-ep01: ratio=${ratio} is not one of ${META.ratios.join(', ')}`);
for (const k of ['style', 'emotion'])
  if (q.has(k) && q.get(k) !== META[k]) throw new Error(`gita-ep01: ${k}=${q.get(k)} cannot be applied; this scene is ${k} ${META[k]} only`);
const [OW, OH] = SIZE[ratio];
if (innerWidth !== OW || innerHeight !== OH)
  throw new Error(`gita-ep01: viewport ${innerWidth}x${innerHeight} does not match ratio ${ratio}; render with --size ${OW}x${OH}`);
const K = AUTHORED / seconds;                                  // authored seconds per output second
const r3 = x => Math.round(x * 1000) / 1000;

const gl = document.createElement('canvas'); gl.width = AW; gl.height = AH;
const comp = makeComp(gl);
const out = document.getElementById('c'); out.width = OW; out.height = OH;
const ox = out.getContext('2d'); ox.imageSmoothingQuality = 'high';
const A = layerSet(), B = layerSet(), TMP = layerSet();

// Fonts: never let a missing face abort the page. load() rejects on a 404 face, so guard every one.
async function tryFont(spec, sample) {
  try { await document.fonts.load(spec, sample); return true; }
  catch (e) { console.warn('[font] skipped', spec); return false; }
}
await tryFont('400 40px CormorantSC');
await tryFont('600 40px CormorantSC');
await tryFont('400 40px Cormorant');
await tryFont('40px MaShanZheng', '水');
const hasDeva = await tryFont('500 52px NotoSerifDeva', 'धर्म');

const NOSUB = q.has('nosub') || q.has('poster');

const S = await import('./shots.js');
await S.init(TMP);
window.DUR = seconds;
window.EV = S.events().map(e => ({ ...e, t: r3(e.t / K), ...(e.dur ? { dur: r3(e.dur / K) } : {}) }));
window.VO = VO.map(v => ({ id: v.id, t: r3(v.sub[0] / K), end: r3(v.sub[1] / K), text: v.text, lang: 'sa' }));

// Cover-crop window (authored px): full height or width, centred on the shot's subject, never past the picture.
const SC = Math.max(OW / AW, OH / AH), CW = OW / SC, CH = OH / SC;
const crop = ta => [clamp(S.subjectX(ta) - CW / 2, 0, AW - CW), (AH - CH) / 2];

// The shloka is an inscription in the blank paper of each shot; shrunk if it would overrun the crop.
function devSub(ctx, text, x, y, k, size, maxW) {
  if (k <= 0) return;
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = clamp(k) * .9;
  ctx.fillStyle = '#1a1410';
  const font = s => `${hasDeva ? 500 : 400} ${s}px ${hasDeva ? 'NotoSerifDeva' : 'CormorantSC'}, serif`;
  ctx.font = font(size);
  const w = ctx.measureText(text).width;
  if (w > maxW) ctx.font = font(Math.floor(size * maxW / w));
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText(text, x, y);
  ctx.restore();
}

window.render = t => {
 try {
  const ta = t * K;
  const [cx, cy] = crop(ta);
  A.clear(); B.clear();
  const o = S.frame(ta, A, B, TMP) || {};
  if (!NOSUB) {
    for (const v of VO) {
      const [a, b] = v.sub;
      if (ta < a || ta > b) continue;
      const k = Math.min(clamp((ta - a) / .45), clamp((b - ta) / .5));
      const pos = S.subPos(v.id, ta), m = pos[0] * CW / AW;   // keep the authored left margin, in proportion
      devSub(A.cd, v.text, cx + m, cy + pos[1] * CH / AH, k, pos[2] || 52, CW - 2 * m);
    }
  }
  comp(A, B, o);
  ox.drawImage(gl, cx, cy, CW, CH, 0, 0, OW, OH);
 } catch (e) {
   console.error('[RENDERFAULT t=' + t + '] ' + e.message);
   console.error(e.stack);
 }
};

window.READY = true;
