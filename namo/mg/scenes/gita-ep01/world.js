// NAMO world — Hastinapur throne hall + Kurukshetra, in xieyi ink.
// Same brush grammar as the ink-wash style: forms are loaded strokes and wet washes,
// most of the frame is empty paper (liubai), one vermilion seal only.
import { mk, draw, blot, mass, qpts, reseed } from '/styles/ink-wash/demo/ink.js';
import { seal } from '/styles/ink-wash/demo/seal.js';
import { T } from './story.js';
import { clamp, lerp, ss, eio, eo, mulberry } from '/core/lib.js';

export const WW = 5600, WH = 1080;
// the hall runs right→left: throne end (right), long colonnade (middle), the far dark door (left)
export const THRONE = [4180, 780];
export const SANJAY = [3540, 806];
export const FAR_DOOR = [980, 700];

let LAY = null;
const cv = (w = WW, h = WH) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
// a layer is {wet, dry, col} canvases + their 2d contexts, matching comp.js layerSet()
function layer() {
  const wet = cv(), dry = cv(), col = cv();
  return { wet, dry, col, cw: wet.getContext('2d'), cd: dry.getContext('2d'), cc: col.getContext('2d') };
}

// ---------- architecture drawn as strokes ----------
// A pillar as ink: two loaded vertical strokes, a capital stroke, a base stroke.
function pillar(ink, x, y0, y1, w, tone) {
  const L = ink.cw;
  draw(L, mk([[x - w, y0], [x - w * .92, (y0 + y1) / 2], [x - w * 1.04, y1]], { w: w * .55, dry: .3, seed: 11, tone }), 1);
  draw(L, mk([[x + w, y0], [x + w * .94, (y0 + y1) / 2], [x + w * 1.02, y1]], { w: w * .5, dry: .35, seed: 12 }), 1);
  draw(L, mk([[x - w * 1.5, y0], [x, y0 - w * .5], [x + w * 1.5, y0]], { w: w * .7, dry: .5, seed: 13 }), 1);
  draw(L, mk([[x - w * 1.6, y1], [x, y1 + w * .3], [x + w * 1.6, y1]], { w: w * .6, dry: .55, seed: 14 }), 1);
  // damp wash behind the shaft: the hall's depth
  L.globalAlpha = .12 * tone; L.fillStyle = '#000';
  L.fillRect(x - w * .85, y0, w * 1.7, y1 - y0); L.globalAlpha = 1;
}

// The peacock throne: a broad mass, a high back, two armrests, drawn as one ordered mass.
function throne(ink, cx, y) {
  const poly = [[cx - 210, y], [cx - 190, y - 250], [cx - 120, y - 330], [cx, y - 360],
                [cx + 120, y - 330], [cx + 190, y - 250], [cx + 210, y]];
  mass(ink.cw, poly, .58, .35, 21);
  // armrests: a heavy stroke each, the dark side set
  draw(ink.cw, mk([[cx - 200, y - 120], [cx - 140, y - 150], [cx - 70, y - 140]], { w: 26, dry: .3, seed: 31 }), 1);
  draw(ink.cw, mk([[cx + 200, y - 120], [cx + 140, y - 150], [cx + 70, y - 140]], { w: 24, dry: .3, seed: 32 }), 1);
  // back crest
  draw(ink.cd, mk([[cx - 60, y - 372], [cx, y - 410], [cx + 60, y - 372]], { w: 30, dry: .65, seed: 33 }), 1);
}

// A hanging lamp: a blot, a thread stroke, a warm halo in the colour layer.
function lamp(colL, inkL, x, y, r) {
  draw(inkL.cw, mk([[x, 0], [x, y - r * 1.4]], { w: 1.6, dry: .5, seed: 41 }), .5);
  blot(inkL.cw, x, y, r, .72, 0, 1, 41);
  const col = colL.cc;
  col.save(); col.globalCompositeOperation = 'lighter';
  const g = col.createRadialGradient(x, y, 0, x, y, r * 7);
  g.addColorStop(0, 'rgba(196,120,40,.30)'); g.addColorStop(1, 'rgba(196,120,40,0)');
  col.fillStyle = g; col.beginPath(); col.arc(x, y, r * 7, 0, 7); col.fill(); col.restore();
}

export function init() {
  if (LAY) return;
  LAY = { arch: layer(), lamps: layer(), floor: layer(), dust: layer(), field: layer() };

  // --- hall architecture ---
  const A = LAY.arch;
  // colonnade: twelve pillars receding to the left, each smaller and fainter
  for (let i = 0; i < 12; i++) {
    const x = 4380 - i * 300;
    const s = 1 - i * .062;
    pillar(A, x, 180 * s + 60, 880 - i * 6, 34 * s, 1 - i * .062);
  }
  // floor: one long wet wash, dark at the throne end, dissolving left
  const F = LAY.floor;
  F.cw.save();
  const fg = F.cw.createLinearGradient(4400, 0, 600, 0);
  fg.addColorStop(0, 'rgba(20,16,12,.42)'); fg.addColorStop(.55, 'rgba(20,16,12,.20)'); fg.addColorStop(1, 'rgba(20,16,12,0)');
  F.cw.fillStyle = fg; F.cw.fillRect(560, 870, 3900, 210); F.cw.restore();
  // the far door: a dark rectangle blotted in, the vanishing point
  blot(F.cw, FAR_DOOR[0], FAR_DOOR[1] + 120, 190, .30, 0, 1, 51);
  F.cw.fillRect(FAR_DOOR[0] - 90, FAR_DOOR[1] - 60, 180, 300);
  F.cw.globalAlpha = 1;

  // lamps
  const Lm = LAY.lamps, Lc = LAY.lamps;
  for (let i = 0; i < 7; i++) lamp(Lc, Lm, 4300 - i * 420, 200, 16 - i * 1.2);

  // --- the vision: Kurukshetra, drawn into the same ink ---
  const V = LAY.field;
  // horizon: one long dragged stroke
  draw(V.cw, mk([[600, 640], [2000, 630], [3600, 620], [4800, 615]], { w: 4, dry: .8, seed: 61 }), 1);
  // the two armies: repeated identical blots (isotype logic, in ink)
  const R = mulberry(77);
  for (let i = 0; i < 90; i++) {
    const x = 800 + i * 42 + R() * 20, y = 660 + R() * 40;
    blot(V.cw, x, y, 5 + R() * 4, .38 + R() * .2, R() * 3, 1, i);
  }
  for (let i = 0; i < 70; i++) {
    const x = 1500 + i * 46 + R() * 20, y = 700 + R() * 44;
    blot(V.cw, x, y, 5 + R() * 4, .34 + R() * .2, R() * 3, 1, 900 + i);
  }
  // dust: a pale wash between them
  V.cw.save();
  const dg = V.cw.createLinearGradient(0, 620, 0, 800);
  dg.addColorStop(0, 'rgba(30,24,18,.02)'); dg.addColorStop(.5, 'rgba(30,24,18,.16)'); dg.addColorStop(1, 'rgba(30,24,18,.02)');
  V.cw.fillStyle = dg; V.cw.fillRect(700, 620, 4100, 190); V.cw.restore();
  // standards: a few upright strokes with a flag blot
  for (let i = 0; i < 8; i++) {
    const x = 900 + i * 480, y = 600;
    draw(V.cd, mk([[x, y], [x + 2, y - 110]], { w: 3, dry: .6, seed: 70 + i }), 1);
    blot(V.cw, x + 16, y - 100, 13, .5, 0, .55, 80 + i);
  }
}

export function camXf(t) {
  // handscroll: the camera pans left as the king speaks; a slow push at the visionary shots
  const p = clamp((t - T.hallIn) / (T.close - T.hallIn));
  const x = lerp(4300, 1200, eio(p));
  const z = 1 + .04 * Math.sin(p * Math.PI);
  return { x, y: 0, z };
}

export function blit(L, cam) {
  const { ink } = L;
  for (const k of ['wet', 'dry']) {
    const c = ink[k].canvas;
    ink[k].setTransform(1, 0, 0, 1, 0, 0);
    ink[k].clearRect(0, 0, c.width, c.height);
  }
  return L;
}

export function layers() { return LAY; }

export function renderOpen(A, t) {
  const cam = camXf(t);
  const S = A.cw;
  S.save(); S.setTransform(1, 0, 0, 1, 0, 0);
  S.translate(960, 540); S.scale(cam.z, cam.z); S.translate(-cam.x, -540);
  S.drawImage(LAY.arch.wet, 0, 0);
  S.drawImage(LAY.arch.dry, 0, 0);
  S.drawImage(LAY.floor.wet, 0, 0);
  S.drawImage(LAY.lamps.wet, 0, 0);
  S.save(); S.globalCompositeOperation = 'lighter';
  S.drawImage(LAY.lamps.col, 0, 0);
  S.restore();
  S.restore();
  return { paper: [0, 0, 1], bleed: 2.4, rim: .5, warm: .04 };
}
