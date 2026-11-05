// NAMO Gita 1.1 — page entry. Contract: window.READY, window.render(t), window.DUR, window.EV.
import { makeComp, layerSet } from '/styles/ink-wash/demo/comp.js';
import { DUR, VO } from './story.js';
import { clamp } from '/core/lib.js';

const q = new URLSearchParams(location.search);
const comp = makeComp(document.getElementById('c'));
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
window.DUR = DUR;
window.EV = S.events();

// The shloka is an inscription in the blank paper of each shot.
function devSub(ctx, text, x, y, k, size) {
  if (k <= 0) return;
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = clamp(k) * .9;
  ctx.fillStyle = '#1a1410';
  ctx.font = `${hasDeva ? 500 : 400} ${size}px ${hasDeva ? 'NotoSerifDeva' : 'CormorantSC'}, serif`;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText(text, x, y);
  ctx.restore();
}

window.render = t => {
 try {
  A.clear(); B.clear();
  const o = S.frame(t, A, B, TMP) || {};
  if (!NOSUB) {
    for (const v of VO) {
      const [a, b] = v.sub;
      if (t < a || t > b) continue;
      const k = Math.min(clamp((t - a) / .45), clamp((b - t) / .5));
      const pos = S.subPos(v.id, t);
      devSub(A.cd, v.text, pos[0], pos[1], k, pos[2] || 52);
    }
  }
  comp(A, B, o);
 } catch (e) {
   console.error('[RENDERFAULT t=' + t + '] ' + e.message);
   console.error(e.stack);
 }
};

window.READY = true;
