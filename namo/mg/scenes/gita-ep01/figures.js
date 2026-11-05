// NAMO figures — Dhritarashtra and Sanjay, in the same loaded-stroke grammar.
// A figure is NOT an outline: it is a robe wash, a few contour strokes, a head blot,
// and one dark accent where the weight sits.
import { mk, draw, blot, mass } from '/styles/ink-wash/demo/ink.js';
import { clamp, lerp, ss, eio } from '/core/lib.js';

// seated old king: heavy, wide, hands on the armrests, head sunk
export function dhritarashtra(L, x, y, s = 1, tone = 1) {
  const wet = L.cw, dry = L.cd;
  // robe mass — one wet wash, heavier at the bottom
  mass(wet, [[x - 120 * s, y], [x - 96 * s, y - 150 * s], [x - 40 * s, y - 210 * s],
             [x + 40 * s, y - 210 * s], [x + 96 * s, y - 150 * s], [x + 120 * s, y]], .52 * tone, .3, 101);
  // shoulders: two loaded strokes, the dark side on the outside
  draw(wet, mk([[x - 96 * s, y - 168 * s], [x - 30 * s, y - 196 * s], [x + 30 * s, y - 196 * s], [x + 96 * s, y - 168 * s]],
       { w: 22 * s, dry: .28, seed: 102 }), 1);
  // head: a blot, slightly forward
  blot(wet, x + 6 * s, y - 250 * s, 34 * s, .80 * tone, .1, .92, 103);
  // crown: a dry stroke arc above the head
  draw(dry, mk([[x - 34 * s, y - 278 * s], [x + 6 * s, y - 300 * s], [x + 40 * s, y - 278 * s]], { w: 12 * s, dry: .7, seed: 104 }), 1);
  // beard: dry fast strokes, flying white
  for (let i = 0; i < 5; i++)
    draw(dry, mk([[x - 16 * s + i * 8 * s, y - 232 * s], [x - 12 * s + i * 8 * s, y - 176 * s]], { w: 7 * s, dry: .85, seed: 110 + i }), .8);
  // arms resting on the armrests
  draw(wet, mk([[x - 96 * s, y - 168 * s], [x - 140 * s, y - 130 * s], [x - 150 * s, y - 96 * s]], { w: 20 * s, dry: .3, seed: 120 }), 1);
  draw(wet, mk([[x + 96 * s, y - 168 * s], [x + 140 * s, y - 130 * s], [x + 150 * s, y - 96 * s]], { w: 20 * s, dry: .3, seed: 121 }), 1);
  // hands: two small dense blots (the dark accent)
  blot(wet, x - 150 * s, y - 94 * s, 13 * s, .92, .3, .8, 122);
  blot(wet, x + 150 * s, y - 94 * s, 13 * s, .92, .3, .8, 123);
  // blind eyes: two pale dry dashes inside the head blot — nothing sharp
  draw(dry, mk([[x - 12 * s, y - 254 * s], [x - 2 * s, y - 254 * s]], { w: 4 * s, dry: .9, seed: 124 }), .35);
  draw(dry, mk([[x + 12 * s, y - 254 * s], [x + 22 * s, y - 254 * s]], { w: 4 * s, dry: .9, seed: 125 }), .35);
}

// standing sage: lean, upright, folded hands at the chest, still
export function sanjay(L, x, y, s = 1, tone = 1) {
  const wet = L.cw, dry = L.cd;
  // robe: a tall narrow wash, hem pooling
  mass(wet, [[x - 46 * s, y], [x - 34 * s, y - 190 * s], [x - 22 * s, y - 250 * s],
             [x + 22 * s, y - 250 * s], [x + 34 * s, y - 190 * s], [x + 46 * s, y]], .46 * tone, .28, 201);
  // shoulders
  draw(wet, mk([[x - 34 * s, y - 244 * s], [x, y - 258 * s], [x + 34 * s, y - 244 * s]], { w: 14 * s, dry: .3, seed: 202 }), 1);
  // head: one committed blot, upright
  blot(wet, x, y - 292 * s, 26 * s, .82 * tone, 0, .95, 203);
  // topknot
  blot(wet, x, y - 322 * s, 11 * s, .78, 0, .9, 204);
  // folded hands: a single dense mass at the chest — the gesture IS the stroke
  mass(wet, [[x - 22 * s, y - 196 * s], [x, y - 206 * s], [x + 22 * s, y - 196 * s],
             [x + 16 * s, y - 172 * s], [x - 16 * s, y - 172 * s]], .78 * tone, .22, 205);
  // folded arms: two strokes running from the shoulders into the hands
  draw(wet, mk([[x - 34 * s, y - 242 * s], [x - 40 * s, y - 212 * s], [x - 20 * s, y - 192 * s]], { w: 13 * s, dry: .32, seed: 206 }), 1);
  draw(wet, mk([[x + 34 * s, y - 242 * s], [x + 40 * s, y - 212 * s], [x + 20 * s, y - 192 * s]], { w: 13 * s, dry: .32, seed: 207 }), 1);
  // uttariya: one long dry diagonal across the chest
  draw(dry, mk([[x - 30 * s, y - 248 * s], [x + 4 * s, y - 200 * s], [x + 26 * s, y - 150 * s]], { w: 15 * s, dry: .72, seed: 208 }), .85);
  // mala: a light dotted line — tiny blots, not a stroke
  for (let i = 0; i < 9; i++) {
    const u = i / 8, ang = Math.PI * (.15 + .7 * u);
    blot(wet, x + Math.cos(ang) * 30 * s, y - 236 * s + Math.sin(ang) * 34 * s, 2.6 * s, .55, 0, 1, 220 + i);
  }
}

// the lone chariot: silhouette, banner, high horse heads — read at a glance
export function chariot(L, x, y, s = 1, tone = 1) {
  const wet = L.cw, dry = L.cd;
  // wheel: a ring made of two arcs, not a circle
  draw(wet, mk([[x - 40 * s, y - 40 * s], [x - 56 * s, y], [x - 40 * s, y + 40 * s]], { w: 7 * s, dry: .4, seed: 301 }), 1);
  draw(wet, mk([[x + 40 * s, y - 40 * s], [x + 56 * s, y], [x + 40 * s, y + 40 * s]], { w: 7 * s, dry: .4, seed: 302 }), 1);
  // body + driver mass
  mass(wet, [[x - 60 * s, y - 20 * s], [x + 10 * s, y - 60 * s], [x + 50 * s, y - 46 * s], [x + 44 * s, y - 4 * s], [x - 56 * s, y + 6 * s]], .6 * tone, .25, 303);
  // banner: one stroke and a blot
  draw(dry, mk([[x + 30 * s, y - 60 * s], [x + 26 * s, y - 150 * s]], { w: 4 * s, dry: .6, seed: 304 }), 1);
  blot(wet, x + 44 * s, y - 138 * s, 18 * s, .62, .1, .6, 305);
  // horse heads: two high abbreviated strokes
  draw(wet, mk([[x + 74 * s, y - 46 * s], [x + 92 * s, y - 92 * s], [x + 84 * s, y - 108 * s]], { w: 9 * s, dry: .45, seed: 306 }), 1);
  draw(wet, mk([[x + 104 * s, y - 42 * s], [x + 120 * s, y - 86 * s], [x + 112 * s, y - 102 * s]], { w: 9 * s, dry: .45, seed: 307 }), 1);
}
