// NAMO Gita 1.1 — shot scheduling. Picks the shot by time, handles ink-bloom transitions,
// returns compositor parameters and sound events. Deterministic: frame(t) is pure.
import { T, VO, DUR } from './story.js';
import * as W from './world.js';
import * as F from './figures.js';
import { seal } from '/styles/ink-wash/demo/seal.js';
import { clamp, ss, eio } from '/core/lib.js';

export async function init(TMP) { W.init(); }

const L = () => W.layers();

// shot 1: hall, throne end — the king is small, the hall is vast
function shotHall(A, t) {
  const LAY = L(), { ink } = A;
  const cam = W.camXf(t);
  const S = A.cw;
  S.save(); S.setTransform(1, 0, 0, 1, 0, 0);
  S.translate(960, 540); S.scale(cam.z, cam.z); S.translate(-cam.x, -540);
  S.drawImage(LAY.arch.wet, 0, 0);
  S.drawImage(LAY.arch.dry, 0, 0);
  S.drawImage(LAY.floor.wet, 0, 0);
  // the king enters at T.king, drawn by a wipe from the bottom up (painted into existence)
  const kp = ss(clamp((t - T.king) / 2.2));
  if (kp > 0) {
    S.save();
    S.beginPath(); S.rect(0, 900 - 900 * kp, W.WW, 900 * kp); S.clip();
    F.dhritarashtra(A, W.THRONE[0], W.THRONE[1], 1.0, 1);
    S.restore();
  }
  // sanjay enters later, at the left of the throne
  const sp = ss(clamp((t - T.sanjay) / 2.0));
  if (sp > 0) {
    S.save(); S.beginPath(); S.rect(0, 900 - 900 * sp, W.WW, 900 * sp); S.clip();
    F.sanjay(A, W.SANJAY[0], W.SANJAY[1], .92, .92);
    S.restore();
  }
  S.restore();
  // lamps glow on top
  A.cw.save(); A.cw.globalCompositeOperation = 'lighter';
  S.setTransform(1, 0, 0, 1, 0, 0);
  S.translate(960, 540); S.scale(cam.z, cam.z); S.translate(-cam.x, -540);
  S.drawImage(LAY.lamps.col, 0, 0);
  S.restore();
  return { paper: [0, 0, 1], bleed: 2.6, rim: .55, warm: .05 };
}

// shot 2: extreme close-up — the king's blind eyes, shallow, crown edge in frame
function shotEyes(A, t) {
  const S = A.cw, LAY = L();
  const u = clamp((t - T.eyes) / 6);
  const z = 6.2 + .5 * u, cx = W.THRONE[0] + 6, cy = W.THRONE[1] - 250;
  S.save(); S.setTransform(1, 0, 0, 1, 0, 0);
  S.translate(960, 540); S.scale(z, z); S.translate(-cx, -cy);
  F.dhritarashtra(A, W.THRONE[0], W.THRONE[1], 1.0, 1);
  S.restore();
  return { paper: [0, 0, 1.06], bleed: 3.2, rim: .75, warm: .02 };
}

// shot 3: the vision — Kurukshetra blooms INTO the hall air
function shotVision(A, t) {
  const LAY = L(), S = A.cw;
  shotHall(A, t);
  const vp = ss(clamp((t - T.visionA) / (T.visionB - T.visionA)));
  if (vp > 0) {
    A.cw.save(); A.cw.globalAlpha = vp * .92;
    A.cw.setTransform(1, 0, 0, 1, 0, 0);
    A.cw.drawImage(LAY.field.wet, 0, 0);
    A.cw.drawImage(LAY.field.dry, 0, 0);
    A.cw.restore();
  }
  return { paper: [0, 0, 1], bleed: 2.4 * (1 - vp) + 4.2 * vp, rim: .5 + .35 * vp, warm: .05 - .04 * vp };
}

// shot 4: the plain — two armies, standards, dust
function shotField(A, t) {
  const LAY = L(), S = A.cw;
  const u = clamp((t - T.field) / 12);
  const cx = 2600 + 900 * Math.sin(u * Math.PI * .6), z = 1.0 + .10 * u;
  S.save(); S.setTransform(1, 0, 0, 1, 0, 0);
  S.translate(960, 540); S.scale(z, z); S.translate(-(cx - 960), -540);
  S.drawImage(LAY.field.wet, 0, 0);
  S.drawImage(LAY.field.dry, 0, 0);
  S.restore();
  return { paper: [0, 0, 1.02], bleed: 2.8, rim: .6, warm: .01 };
}

// shot 5: the lone chariot at sunrise
function shotChariot(A, t) {
  const LAY = L(), S = A.cw;
  const u = clamp((t - T.chariot) / 6);
  const g = S.createRadialGradient(2300, 560, 20, 2300, 560, 900);
  g.addColorStop(0, 'rgba(198,128,48,.16)'); g.addColorStop(1, 'rgba(198,128,48,0)');
  S.save(); S.setTransform(1, 0, 0, 1, 0, 0);
  S.drawImage(LAY.field.wet, 0, 0);
  S.globalCompositeOperation = 'lighter'; S.fillStyle = g; S.fillRect(0, 0, 1920, 1080);
  S.globalCompositeOperation = 'source-over';
  F.chariot(A, 2300 + u * 40, 700, 1.15, .95);
  S.restore();
  return { paper: [0, 0, 1.04], bleed: 3.0, rim: .65, warm: .06 };
}

// shot 6: over Sanjay's shoulder — the king small and alone at the far end
function shotClose(A, t) {
  const LAY = L(), S = A.cw;
  const u = clamp((t - T.close) / 5);
  const z = 1.0 + .06 * u;
  S.save(); S.setTransform(1, 0, 0, 1, 0, 0);
  S.translate(960, 540); S.scale(z, z); S.translate(-(3800 + u * 60), -540);
  S.drawImage(LAY.arch.wet, 0, 0); S.drawImage(LAY.floor.wet, 0, 0);
  F.dhritarashtra(A, W.THRONE[0], W.THRONE[1], 1.0, .9);
  // Sanjay's shoulder, very near, dark — the frame's foreground
  S.globalAlpha = .55;
  F.sanjay(A, 3450, 900, 1.35, .55);
  S.restore();
  return { paper: [0, 0, .98], bleed: 2.2, rim: .4, warm: .03 };
}

export function frame(t, A, B, TMP) {
  if (t < T.hallIn) return { paper: [0, 0, 1], bleed: 2.2, rim: .5, warm: .05 };
  if (t < T.king) return shotHall(A, t);
  if (t < T.eyes) return shotHall(A, t);
  if (t < T.eyes + 6.4) return shotEyes(A, t);
  if (t < T.visionA) return shotHall(A, t);
  if (t < T.field) return shotVision(A, t);
  if (t < T.chariot) return shotField(A, t);
  if (t < T.close) return shotChariot(A, t);
  return shotClose(A, t);
}

export function subPos(id, t) {
  // each shot's liubai (left blank space) — the inscription goes where the paper is empty
  switch (id) {
    case 'S1': return [150, 880, 52];
    case 'S2': return [150, 860, 52];
    case 'S3': return [150, 900, 52];
    case 'S4': return [150, 880, 52];
    case 'S5': return [150, 900, 52];
    default: return [150, 880, 52];
  }
}

export function events() {
  return [
    { t: T.dropHit, type: 'pluck', f: 220, g: .10 },
    { t: T.hallIn, type: 'whoosh', dur: 1.2 },
    { t: T.king, type: 'thump' },
    { t: T.sanjay, type: 'chime', f: 440, g: .07 },
    { t: T.visionA, type: 'riser', dur: 3.0 },
    { t: T.field, type: 'pad', dur: 8, f: [110, 138.6, 164.8], g: .05 },
    { t: T.chariot, type: 'chime', f: 660, g: .05 },
    { t: T.close, type: 'pad', dur: 5, f: [98, 130.8], g: .06 },
  ];
}
