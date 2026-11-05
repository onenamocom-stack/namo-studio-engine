// NAMO explainer: one beats JSON -> a motion-graphics film at any ratio. Style numbers: ../STYLE.md
import React, { createContext, useContext } from 'react';
import { Fill, Sequence, useFrame, useCompositionConfig, interpolate, spring, Easing } from '@rendiv/core';

const C = {
  bgEdge: '#07080F', bgMid: '#111434', text: '#F5F7FF', dim2: '#8A90B8', dim: '#4A5080',
  cyan: '#00B8F7', red: '#FF543F', amber: '#FBBF24', teal: '#14B8A6',
  card: '#101433', border: '#1C2150',
} as const;
type Tone = 'cyan' | 'red' | 'amber' | 'teal' | 'dim2';
const tone = (c?: Tone) => C[c ?? 'cyan'];
const SANS = 'Inter, "Noto Sans Devanagari", sans-serif';
const SERIF = '"Noto Serif Devanagari", "Noto Sans Devanagari", serif';
const MONO = '"JetBrains Mono", "Noto Sans Devanagari", monospace';
const OUT = Easing.bezier(0.16, 1, 0.3, 1);
const ENTER = 14, EXIT = 8;
// Reveals are authored on a design clock of 180 frames (6 s @ 30 fps). Every beat maps its own
// length onto that clock, so a reveal lands at the same fraction of a short or a long beat.
const DESIGN = 180, DFPS = 30;
const DEVA = /[\u0900-\u097F]/;
const CLAMP = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

// u: layout unit, tu: type unit (both px). Landscape scales up so content fills ~2/3 of the frame.
type Stage = { u: number; tu: number; W: number; H: number; portrait: boolean; fps: number };
const S = createContext<Stage>({ u: 14.6, tu: 14.6, W: 1920, H: 1080, portrait: false, fps: 30 });
// real seconds since the beat started: idle motion runs on this, so holds never freeze
const T = createContext(0);

const prog = (f: number, start: number, len = ENTER) =>
  interpolate(f, [start, start + len], [0, 1], { ...CLAMP, easing: OUT });
const pop = (f: number, start: number) =>
  spring({ frame: Math.max(0, f - start), fps: DFPS, config: { damping: 14, stiffness: 140, mass: 1 } }) * (f >= start ? 1 : 0);
const rise = (p: number, u: number): React.CSSProperties => ({
  opacity: p, transform: `translateY(${(1 - p) * 1.6 * u}px)`, filter: p < 0.99 ? `blur(${(1 - p) * 6}px)` : undefined,
});
const glow = (c: string, r = 24) => `0 0 ${r}px ${c}88`;
// 0..1 sine, `period` seconds
const wave = (t: number, period: number, phase = 0) => 0.5 + 0.5 * Math.sin((t / period + phase) * 2 * Math.PI);
const clean = (w: string) => w.replace(/[‘’“”"'?,.।॥:;!]/g, '');
const graphemes = (s: string) => [...new Intl.Segmenter('hi', { granularity: 'grapheme' }).segment(s)].map((g) => g.segment);

// ---------- shared pieces ----------
const Overline: React.FC<{ text: string; f: number; color?: string }> = ({ text, f, color = C.amber }) => {
  const { u, tu, portrait } = useContext(S);
  const deva = DEVA.test(text);
  return (
    <div style={{ ...rise(prog(f, 0), u), font: `600 ${(deva ? (portrait ? 2.8 : 2.2) : 1.7) * tu}px ${MONO}`, color,
      textTransform: 'uppercase', letterSpacing: deva ? '0.06em' : '0.32em', marginBottom: 2.2 * u, textAlign: 'center' }}>◆ {text}</div>
  );
};

const Rule: React.FC<{ f: number; start: number }> = ({ f, start }) => {
  const { u, W } = useContext(S);
  const t = useContext(T);
  const w = prog(f, start, 18) * 0.14 * W;
  return (
    <div style={{ position: 'relative', height: 2, width: w, background: C.cyan, boxShadow: glow(C.cyan, 12), margin: `${1.6 * u}px auto` }}>
      <div style={{ position: 'absolute', top: -3, height: 8, width: '14%', left: `${((t / 2.4) % 1) * 86}%`,
        background: 'radial-gradient(closest-side, #fff, transparent)' }} />
    </div>
  );
};

// words of a line, each rising in turn; emphasised words take their colour, a breathing glow and an underline
const Words: React.FC<{ line: string; f: number; start: number; emph?: Record<string, Tone>; step?: number }> =
  ({ line, f, start, emph = {}, step = 5 }) => {
    const { u } = useContext(S);
    const t = useContext(T);
    return (
      <>{line.split(' ').map((w, i) => {
        const c = emph[clean(w)];
        const k = start + i * step;
        return (
          <span key={i} style={{ display: 'inline-block', position: 'relative', marginRight: '0.28em', ...rise(prog(f, k), u),
            color: c ? tone(c) : undefined, textShadow: c ? glow(tone(c), 12 + 24 * wave(t, 2.2, i * 0.17)) : undefined }}>
            {w}
            {c && <span style={{ position: 'absolute', left: 0, bottom: '0.04em', height: Math.max(3, 0.28 * u), borderRadius: 2,
              width: `${prog(f, k + 12, 16) * 100}%`, background: tone(c), boxShadow: glow(tone(c), 10) }} />}
          </span>
        );
      })}</>
    );
  };

const Typed: React.FC<{ text: string; f: number; start: number; cps?: number }> = ({ text, f, start, cps = 22 }) => {
  const t = useContext(T);
  const g = graphemes(text);
  const n = Math.max(0, Math.min(g.length, Math.floor(((f - start) / DFPS) * cps)));
  if (f < start) return null;
  return (
    <span>{g.slice(0, n).join('')}
      <span style={{ display: 'inline-block', width: 2, height: '1em', verticalAlign: '-0.12em', marginLeft: 4,
        background: C.cyan, opacity: n < g.length || Math.floor(t * 2) % 2 === 0 ? 1 : 0 }} /></span>
  );
};

// a card: lit cards breathe, every card carries a slow sheen sweep
const Card: React.FC<{ children: React.ReactNode; active?: string; style?: React.CSSProperties }> = ({ children, active, style }) => {
  const { u } = useContext(S);
  const t = useContext(T);
  const g = wave(t, 2.6);
  return (
    <div style={{ position: 'relative', overflow: 'hidden', background: `linear-gradient(180deg, #131845, ${C.card})`,
      border: `1px solid ${active ?? C.border}`, borderRadius: 1.4 * u,
      boxShadow: active ? `0 0 ${(1.4 + 2 * g) * u}px ${active}66, 0 ${u}px ${3 * u}px #0008` : `0 ${u}px ${3 * u}px #0008`,
      padding: `${2 * u}px ${2.4 * u}px`, ...style }}>
      <div style={{ position: 'absolute', top: 0, bottom: 0, width: '30%', left: `${((t / 3.4) % 1) * 260 - 80}%`,
        background: 'linear-gradient(100deg, transparent, #ffffff0c, transparent)' }} />
      {children}
    </div>
  );
};

// ---------- beat types (beats/*.json) ----------
type MapNode = { id: string; label: string; sub?: string; parent?: string; tag?: string; color?: Tone };
type Link = { from: string; to: string; label?: string; dashed?: boolean; color?: Tone };
type Side = { head: string; sub: string; color: Tone };
export type Beat = { id: string; t: number; dur: number; chapter: string; overline: string; caption?: string; vo?: string } & (
  | { type: 'title'; lines: string[]; emph?: Record<string, Tone>; sub?: string; mark?: string }
  | { type: 'kinetic'; lines: string[]; emph?: Record<string, Tone>; serif?: boolean; note?: string }
  | { type: 'flow'; nodes: { label: string; sub?: string }[]; arrows: string[] }
  | { type: 'map'; nodes: MapNode[]; links?: Link[] }
  | { type: 'compare'; left: Side; right: Side; stamp: string }
  | { type: 'number'; value: number; prefix?: string; color?: Tone; label: string; sub?: string }
  | { type: 'timeline'; items: { k: string; label: string }[] }
  | { type: 'recap'; items: string[]; footer?: string });
export type Doc = { title: string; lang?: string; chapters: { id: string; title: string }[]; beats: Beat[] };
type BP<K extends Beat['type']> = { b: Extract<Beat, { type: K }>; f: number };

const Title: React.FC<BP<'title'>> = ({ b, f }) => {
  const { u, tu, portrait } = useContext(S);
  const t = useContext(T);
  return (
    <div style={{ textAlign: 'center', position: 'relative' }}>
      {b.mark && <div style={{ position: 'absolute', left: '50%', top: '50%', whiteSpace: 'nowrap',
        transform: `translate(-50%,-50%) translateX(${-t * 0.6 * u}px) scale(${1 + 0.02 * t})`,
        font: `800 ${(portrait ? 34 : 40) * tu}px ${MONO}`, color: C.cyan, opacity: 0.05 * prog(f, 0, 30) }}>{b.mark}</div>}
      <Overline text={b.overline} f={f} />
      {b.lines.map((l, i) => (
        <div key={i} style={{ font: `700 ${(portrait ? 7 : 9.5) * tu}px ${SANS}`, lineHeight: 1.25, color: C.text }}>
          <Words line={l} f={f} start={8 + i * 12} emph={b.emph} />
        </div>
      ))}
      <Rule f={f} start={34} />
      <div style={{ ...rise(prog(f, 44), u), font: `600 ${2 * tu}px ${MONO}`, color: C.dim2, letterSpacing: '0.2em' }}>{b.sub}</div>
    </div>
  );
};

const Kinetic: React.FC<BP<'kinetic'>> = ({ b, f }) => {
  const { u, W, portrait, tu } = useContext(S);
  const per = b.serif ? 4 : 6;
  let at = 8;
  const starts = b.lines.map((l) => { const s = at; at += l.split(' ').length * per + 8; return s; });
  return (
    <div style={{ textAlign: 'center', maxWidth: portrait ? 0.9 * W : 0.8 * W }}>
      <Overline text={b.overline} f={f} />
      {b.lines.map((l, i) => (
        <div key={i} style={{ font: b.serif ? `600 ${(portrait ? 5.6 : 6.6) * tu}px ${SERIF}` : `700 ${(portrait ? 5.8 : 7.2) * tu}px ${SANS}`,
          lineHeight: 1.45, color: C.text }}>
          <Words line={l} f={f} start={starts[i]} emph={b.emph} step={per} />
        </div>
      ))}
      {b.note && (b.serif
        ? <div style={{ ...rise(prog(f, at + 6), u), marginTop: 2.4 * u, font: `500 ${(portrait ? 1.9 : 1.7) * tu}px ${MONO}`, color: C.dim2, lineHeight: 1.6 }}>{b.note}</div>
        : <div style={{ marginTop: 3 * u, font: `700 ${(portrait ? 3.6 : 3.8) * tu}px ${SANS}`, color: C.cyan, minHeight: 4.8 * u }}>
            <Typed text={b.note} f={f} start={at + 8} /></div>)}
    </div>
  );
};

// a connector that draws on, then carries a travelling light packet while the beat holds
const Arrow: React.FC<{ p: number; vertical: boolean; len: number; label: string }> = ({ p, vertical, len, label }) => {
  const { u, tu } = useContext(S);
  const t = useContext(T);
  const w = vertical ? 2 * u : len, h = vertical ? len : 2 * u, L = len - u;
  const q = (t / 1.4) % 1;
  return (
    <div style={{ position: 'relative', width: w, height: h, flex: 'none' }}>
      <svg width={w} height={h} style={{ overflow: 'visible' }}>
        <line x1={vertical ? u : 0} y1={vertical ? 0 : u} x2={vertical ? u : L} y2={vertical ? L : u} stroke={C.cyan} strokeWidth={2.5}
          strokeDasharray={`${L} ${L}`} strokeDashoffset={L * (1 - p)} />
        <polygon points={vertical ? `${u - 8},${len - u - 4} ${u + 8},${len - u - 4} ${u},${len}`
          : `${len - u - 4},${u - 8} ${len - u - 4},${u + 8} ${len},${u}`} fill={C.cyan} opacity={p > 0.9 ? 1 : 0} />
        {p >= 1 && <circle cx={vertical ? u : q * L} cy={vertical ? q * L : u} r={0.45 * u} fill="#fff"
          opacity={Math.sin(q * Math.PI)} style={{ filter: `drop-shadow(0 0 ${0.8 * u}px ${C.cyan})` }} />}
      </svg>
      <div style={{ position: 'absolute', font: `500 ${2.2 * tu}px ${SANS}`, color: C.cyan, lineHeight: 1.3, textAlign: 'center',
        opacity: interpolate(p, [0.5, 1], [0, 1], CLAMP),
        ...(vertical ? { left: 3.4 * u, top: '50%', transform: 'translateY(-50%)', whiteSpace: 'nowrap' }
          : { left: '50%', bottom: 2.6 * u, transform: 'translateX(-50%)', width: L }) }}>{label}</div>
    </div>
  );
};

const NodeCard: React.FC<{ label: string; sub?: string; s: number; color?: Tone; width: number; tag?: string; lit?: boolean }> =
  ({ label, sub, s, color, width, tag, lit }) => {
    const { u, tu } = useContext(S);
    return (
      <div style={{ width, transform: `scale(${0.86 + 0.14 * s})`, opacity: Math.min(1, s * 1.4), flex: 'none' }}>
        <Card active={lit ? tone(color) : undefined} style={{ textAlign: 'center', padding: `${1.8 * u}px ${1.4 * u}px` }}>
          <div style={{ font: `700 ${3.8 * tu}px ${SANS}`, color: color ? tone(color) : C.text, lineHeight: 1.3 }}>{label}</div>
          {sub && <div style={{ font: `500 ${2 * tu}px ${SANS}`, color: C.dim2, marginTop: 0.6 * u }}>{sub}</div>}
          {tag && <div style={{ display: 'inline-block', marginTop: 1.2 * u, padding: `${0.4 * u}px ${1.2 * u}px`, borderRadius: 99,
            font: `600 ${1.9 * tu}px ${MONO}`, color: tone(color), border: `1px solid ${tone(color)}`, background: `${tone(color)}18` }}>{tag}</div>}
        </Card>
      </div>
    );
  };

const Flow: React.FC<BP<'flow'>> = ({ b, f }) => {
  const { u, portrait } = useContext(S);
  const gap = 18; // design frames between steps
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <Overline text={b.overline} f={f} />
      <div style={{ display: 'flex', flexDirection: portrait ? 'column' : 'row', alignItems: 'center', marginTop: 2 * u }}>
        {b.nodes.map((nd, i) => (
          <React.Fragment key={i}>
            {i > 0 && <Arrow p={prog(f, 8 + i * 2 * gap - gap, 16)} vertical={portrait} len={(portrait ? 11 : 17) * u} label={b.arrows[i - 1]} />}
            <NodeCard label={nd.label} sub={nd.sub} s={pop(f, 8 + i * 2 * gap)} width={(portrait ? 56 : 26) * u}
              lit={f >= 8 + i * 2 * gap && (i === b.nodes.length - 1 || f < 8 + (i + 1) * 2 * gap + 30)} />
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

const RelMap: React.FC<BP<'map'>> = ({ b, f }) => {
  const { u, portrait, tu } = useContext(S);
  const t = useContext(T);
  const bw = (portrait ? 88 : 104) * u, bh = (portrait ? 84 : 42) * u, cw = (portrait ? 36 : 34) * u;
  const levels = [b.nodes.filter((n) => !n.parent), b.nodes.filter((n) => n.parent)];
  const pos: Record<string, { x: number; y: number; i: number }> = {};
  let k = 0;
  levels.forEach((lv, li) => lv.forEach((n, i) => {
    const col = li === 0 ? i : levels[0].findIndex((p) => p.id === n.parent);
    pos[n.id] = { x: ((col + 0.5) / levels[0].length) * bw, y: (li === 0 ? 0.2 : 0.74) * bh, i: k++ };
  }));
  const at = (id: string) => 8 + pos[id].i * 16;
  const edges: Link[] = [
    ...b.nodes.flatMap((n) => (n.parent ? [{ from: n.parent, to: n.id, color: n.color }] : [])),
    ...(b.links ?? []).map((l): Link => ({ ...l, color: l.dashed ? 'red' : 'dim2' })),
  ];
  const dashedP = prog(f, 8 + k * 16 + 10, 20);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <Overline text={b.overline} f={f} />
      <div style={{ position: 'relative', width: bw, height: bh }}>
        <svg width={bw} height={bh} style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
          {edges.map((e, i) => {
            const a = pos[e.from], z = pos[e.to];
            const len = Math.hypot(z.x - a.x, z.y - a.y);
            const p = e.dashed ? dashedP : prog(f, Math.max(at(e.from), at(e.to)) - 4, 16);
            const q = (t / 1.8 + i * 0.37) % 1;
            return (
              <g key={i}>
                <line x1={a.x} y1={a.y} x2={z.x} y2={z.y} stroke={tone(e.color)} strokeWidth={2.5}
                  strokeDasharray={e.dashed ? '10 10' : `${len} ${len}`} strokeDashoffset={e.dashed ? -t * 30 : len * (1 - p)}
                  opacity={e.dashed ? p * 0.9 : 0.8} />
                {!e.dashed && p >= 1 && <circle cx={a.x + (z.x - a.x) * q} cy={a.y + (z.y - a.y) * q} r={0.4 * u} fill="#fff"
                  opacity={Math.sin(q * Math.PI)} style={{ filter: `drop-shadow(0 0 ${0.8 * u}px ${tone(e.color)})` }} />}
              </g>
            );
          })}
        </svg>
        {edges.filter((e) => e.label).map((e, i) => {
          const a = pos[e.from], z = pos[e.to];
          const p = e.dashed ? dashedP : prog(f, Math.max(at(e.from), at(e.to)) + 8);
          return <div key={i} style={{ position: 'absolute', left: (a.x + z.x) / 2, top: (a.y + z.y) / 2,
            transform: `translate(-50%, -50%) ${e.dashed ? `rotate(${Math.atan2(z.y - a.y, z.x - a.x)}rad) translateY(-${2 * u}px)` : `translateY(-${2.2 * u}px)`}`,
            opacity: p, font: `600 ${2.1 * tu}px ${SANS}`, color: tone(e.color), whiteSpace: 'nowrap',
            background: C.bgMid, padding: `0 ${0.8 * u}px` }}>{e.label}</div>;
        })}
        {b.nodes.map((n) => (
          <div key={n.id} style={{ position: 'absolute', left: pos[n.id].x, top: pos[n.id].y, transform: 'translate(-50%,-50%)' }}>
            <NodeCard label={n.label} sub={n.sub} tag={n.tag} color={n.color} width={cw} s={pop(f, at(n.id))}
              lit={!!n.color && f > 8 + k * 16 + 10} />
          </div>
        ))}
      </div>
    </div>
  );
};

const Compare: React.FC<BP<'compare'>> = ({ b, f }) => {
  const { u, portrait, tu } = useContext(S);
  const t = useContext(T);
  const side = (s: Side, start: number) => (
    <div style={{ ...rise(prog(f, start), u), flex: 'none' }}>
      <Card active={tone(s.color)} style={{ width: (portrait ? 60 : 40) * u, textAlign: 'center', padding: `${3 * u}px ${2 * u}px` }}>
        <div style={{ font: `700 ${(portrait ? 9 : 10) * tu}px ${SANS}`, color: tone(s.color), lineHeight: 1.35,
          textShadow: glow(tone(s.color), 20 + 20 * wave(t, 2.4, start / 40)) }}>{s.head}</div>
        <div style={{ font: `500 ${3 * tu}px ${SANS}`, color: C.text, marginTop: u }}>{s.sub}</div>
      </Card>
    </div>
  );
  const st = pop(f, 50);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative' }}>
      <Overline text={b.overline} f={f} />
      <div style={{ display: 'flex', flexDirection: portrait ? 'column' : 'row', alignItems: 'center', gap: 3 * u }}>
        {side(b.left, 8)}
        <div style={{ ...rise(prog(f, 18), u), font: `600 ${2.6 * tu}px ${MONO}`, color: C.dim2 }}>बनाम</div>
        {side(b.right, 26)}
      </div>
      {f >= 50 && <div style={{ position: 'absolute', left: '50%', top: portrait ? '58%' : `calc(100% + ${4 * u}px)`,
        transform: `translate(-50%,-50%) rotate(${-8 + 1.5 * Math.sin(t * 2) * st}deg) scale(${1.6 - 0.6 * st})`, opacity: Math.min(1, st * 1.5),
        font: `700 ${6.4 * tu}px ${SANS}`, color: C.red, border: `${0.5 * u}px solid ${C.red}`, borderRadius: u,
        padding: `${0.2 * u}px ${2.4 * u}px`, background: '#1a0b14e6', boxShadow: glow(C.red, 30 + 20 * wave(t, 1.6)), whiteSpace: 'nowrap' }}>{b.stamp}</div>}
    </div>
  );
};

const BigNumber: React.FC<BP<'number'>> = ({ b, f }) => {
  const { u, portrait, W, tu } = useContext(S);
  const t = useContext(T);
  const c = tone(b.color);
  const v = Math.round(b.value * prog(f, 8, 30));
  const r = (t / 2.2) % 1; // ripple ring behind the figure
  return (
    <div style={{ textAlign: 'center', maxWidth: portrait ? 0.9 * W : 0.8 * W }}>
      <Overline text={b.overline} f={f} />
      <div style={{ position: 'relative', font: `800 ${(portrait ? 13 : 22) * tu}px ${MONO}`, color: c, lineHeight: 1.1, whiteSpace: 'nowrap',
        textShadow: glow(c, 30 + 24 * wave(t, 2.2)) }}>
        <div style={{ position: 'absolute', left: '50%', top: '50%', width: (0.3 + 0.7 * r) * 50 * u, height: (0.3 + 0.7 * r) * 50 * u,
          transform: 'translate(-50%,-50%)', borderRadius: '50%', border: `2px solid ${c}`, opacity: (1 - r) * 0.3 * prog(f, 38) }} />
        <span style={{ color: C.cyan, textShadow: glow(C.cyan, 40), opacity: prog(f, 40) }}>{b.prefix}</span>{v}
      </div>
      <div style={{ ...rise(prog(f, 48), u), font: `700 ${(portrait ? 4.2 : 4.2) * tu}px ${SANS}`, color: C.text, marginTop: 2 * u, lineHeight: 1.4 }}>{b.label}</div>
      <div style={{ ...rise(prog(f, 60), u), font: `500 ${2.8 * tu}px ${SANS}`, color: C.dim2, marginTop: u }}>{b.sub}</div>
    </div>
  );
};

const Timeline: React.FC<BP<'timeline'>> = ({ b, f }) => {
  const { u, portrait, tu, W } = useContext(S);
  const t = useContext(T);
  const n = b.items.length, at = (i: number) => 10 + i * 22;
  const fill = interpolate(f, [at(0), at(n - 1)], [0, 1], CLAMP);
  const q = ((t / 2.5) % 1) * fill; // light pulse running along the lit part of the track
  const dot = (i: number) => {
    const s = pop(f, at(i)), lit = f >= at(i);
    return <div style={{ width: 2.4 * u, height: 2.4 * u, borderRadius: '50%', flex: 'none', transform: `scale(${0.5 + 0.5 * s})`,
      background: lit ? C.cyan : C.card, border: `2px solid ${lit ? C.cyan : C.border}`, boxShadow: lit ? glow(C.cyan, 16) : undefined }} />;
  };
  const pulse = { position: 'absolute', width: 1.2 * u, height: 1.2 * u, borderRadius: '50%', background: '#fff',
    boxShadow: glow(C.cyan, 18), opacity: fill > 0 ? 0.9 : 0 } as const;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <Overline text={b.overline} f={f} />
      {portrait ? (
        <div style={{ position: 'relative', width: 84 * u, height: 96 * u, marginTop: 4 * u }}>
          <div style={{ position: 'absolute', background: C.border, left: 11.2 * u, top: 0, width: 3, height: '100%' }} />
          <div style={{ position: 'absolute', background: C.cyan, boxShadow: glow(C.cyan, 10), left: 11.2 * u, top: 0, width: 3, height: `${fill * 100}%` }} />
          <div style={{ ...pulse, left: 11.2 * u - 0.6 * u + 1, top: `calc(${q * 100}% - ${0.6 * u}px)` }} />
          {b.items.map((it, i) => {
            const p = prog(f, at(i) + 2);
            return (
              <div key={i} style={{ position: 'absolute', top: `${(i / (n - 1)) * 100}%`, left: 0, transform: 'translateY(-50%)',
                display: 'flex', alignItems: 'center', gap: 2 * u }}>
                <div style={{ width: 8 * u, textAlign: 'right', font: `600 ${2.2 * tu}px ${MONO}`, color: f >= at(i) ? C.amber : C.dim, opacity: p }}>{it.k}</div>
                {dot(i)}
                <div style={{ ...rise(p, u), font: `700 ${3.3 * tu}px ${SANS}`, color: C.text, width: 64 * u }}>{it.label}</div>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ position: 'relative', width: 0.84 * W, height: 26 * u }}>
          <div style={{ position: 'absolute', background: C.border, top: 7.2 * u, left: '10%', height: 3, width: '80%' }} />
          <div style={{ position: 'absolute', background: C.cyan, boxShadow: glow(C.cyan, 10), top: 7.2 * u, left: '10%', height: 3, width: `${fill * 80}%` }} />
          <div style={{ ...pulse, top: 7.2 * u - 0.6 * u + 1, left: `calc(${10 + q * 80}% - ${0.6 * u}px)` }} />
          {b.items.map((it, i) => {
            const p = prog(f, at(i) + 2);
            return (
              <div key={i} style={{ position: 'absolute', left: `${10 + (i / (n - 1)) * 80}%`, top: 0, width: (0.84 * W * 0.8) / (n - 1) - u,
                transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div style={{ height: 6 * u, display: 'flex', alignItems: 'center', font: `600 ${2.4 * tu}px ${MONO}`,
                  color: f >= at(i) ? C.amber : C.dim, opacity: p }}>{it.k}</div>
                {dot(i)}
                <div style={{ ...rise(p, u), font: `700 ${2.8 * tu}px ${SANS}`, color: C.text, textAlign: 'center', marginTop: 1.6 * u, lineHeight: 1.4 }}>{it.label}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const Recap: React.FC<BP<'recap'>> = ({ b, f }) => {
  const { u, portrait, W, tu } = useContext(S);
  const t = useContext(T);
  const n = b.items.length, landed = f >= 10 + n * 20 + 14;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <Overline text={b.overline} f={f} />
      <Card style={{ width: portrait ? 0.88 * W : 0.7 * W, padding: `${2.4 * u}px ${2.4 * u}px` }}>
        {b.items.map((it, i) => {
          const s = pop(f, 10 + i * 20);
          // once all have landed, a focus band walks down the list
          const h = landed ? Math.max(0, 1 - Math.abs(((t / 1.6) % n) - i - 0.5) * 1.6) : 0;
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 2 * u, marginTop: i ? 1.2 * u : 0, padding: `${0.8 * u}px ${u}px`,
              borderRadius: u, background: `rgba(0,184,247,${0.08 * h})`, ...rise(prog(f, 8 + i * 20), u) }}>
              <div style={{ width: 4 * u, height: 4 * u, flex: 'none', borderRadius: '50%', border: `2px solid ${C.teal}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.teal, font: `800 ${2.2 * tu}px ${SANS}`,
                transform: `scale(${s * (1 + 0.12 * h)})`, background: `${C.teal}18`, boxShadow: h ? glow(C.teal, 20 * h) : undefined }}>✓</div>
              <div style={{ font: `700 ${3.4 * tu}px ${SANS}`, color: C.text, lineHeight: 1.4 }}>{it}</div>
            </div>
          );
        })}
      </Card>
      <div style={{ ...rise(prog(f, 76), u), marginTop: 3 * u, font: `700 ${3.2 * tu}px ${SANS}`, color: C.cyan,
        textShadow: glow(C.cyan), transform: `translateX(${Math.sin(t * 5) * 0.4 * u}px)` }}>{b.footer}</div>
    </div>
  );
};

// a beat: reveals on the design clock, idle motion on real time, push-in for its whole length, quick exit
const BeatView: React.FC<{ b: Beat; n: number }> = ({ b, n }) => {
  const real = useFrame();
  const { u, fps } = useContext(S);
  const f = (real * DESIGN) / n, t = real / fps;
  const out = interpolate(real, [n - EXIT, n], [1, 0], CLAMP);
  const float = Math.sin((t / 5) * 2 * Math.PI) * 0.35 * u;
  return (
    <T.Provider value={t}>
      <Fill style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: out,
        transform: `translateY(${(1 - out) * -u + float}px) scale(${interpolate(real, [0, n], [1, 1.035])})` }}>
        {b.type === 'title' ? <Title b={b} f={f} />
          : b.type === 'kinetic' ? <Kinetic b={b} f={f} />
          : b.type === 'flow' ? <Flow b={b} f={f} />
          : b.type === 'map' ? <RelMap b={b} f={f} />
          : b.type === 'compare' ? <Compare b={b} f={f} />
          : b.type === 'number' ? <BigNumber b={b} f={f} />
          : b.type === 'timeline' ? <Timeline b={b} f={f} />
          : b.type === 'recap' ? <Recap b={b} f={f} />
          : (() => { throw new Error(`beat ${(b as Beat).id}: unknown type "${(b as Beat).type}"`); })()}
      </Fill>
    </T.Provider>
  );
};

// ---------- persistent layers ----------
const Ambient: React.FC = () => {
  const f = useFrame();
  const { W, H, u } = useContext(S);
  const sq = Array.from({ length: 12 }, (_, i) => {
    const r = (k: number) => ((Math.sin(i * 127.1 + k * 311.7) * 43758.5453) % 1 + 1) % 1;
    const x = (r(1) * W + f * (0.15 + r(2) * 0.35)) % W, y = (r(3) * H - f * (0.1 + r(4) * 0.25) + H * 10) % H;
    const s = 0.6 * u + r(5) * 0.6 * u;
    return <div key={i} style={{ position: 'absolute', left: x, top: y, width: s, height: s, border: `1px solid ${r(6) > 0.7 ? C.amber : '#5a64a8'}`,
      opacity: 0.1 + r(7) * 0.2, transform: `rotate(${f * (r(8) - 0.5)}deg)` }} />;
  });
  const sweep = ((f % 240) / 240) * 1.6 - 0.3;
  return (
    <Fill>
      <div style={{ position: 'absolute', inset: 0, background: `radial-gradient(ellipse at 50% 45%, ${C.bgMid} 0%, #0c0e22 45%, ${C.bgEdge} 100%)` }} />
      <div style={{ position: 'absolute', top: '38%', left: `${sweep * 100}%`, width: '40%', height: 1,
        background: `linear-gradient(90deg, transparent, ${C.cyan}44, transparent)` }} />
      {sq}
    </Fill>
  );
};

const Chrome: React.FC<{ doc: Doc; total: number }> = ({ doc, total }) => {
  const f = useFrame();
  const { u, fps, portrait } = useContext(S);
  const t = f / fps;
  const beat = doc.beats.find((b) => t >= b.t && t < b.t + b.dur) ?? doc.beats[doc.beats.length - 1];
  const ci = doc.chapters.findIndex((c) => c.id === beat.chapter);
  const bf = f - Math.round(beat.t * fps);
  const capP = prog(bf, 6, 12) * interpolate(bf, [beat.dur * fps - EXIT, beat.dur * fps], [1, 0], CLAMP);
  const top = (portrait ? 7 : 3) * u, side = (portrait ? 6 : 4) * u;
  return (
    <Fill>
      <div style={{ position: 'absolute', left: side, right: side, top, height: 2, background: '#1a1e40' }}>
        <div style={{ height: 2, width: `${(t / total) * 100}%`, background: C.cyan, boxShadow: glow(C.cyan, 8) }} />
        {doc.chapters.map((c, i) => (
          <div key={c.id} style={{ position: 'absolute', left: `${((doc.beats.find((b) => b.chapter === c.id)?.t ?? 0) / total) * 100}%`,
            top: -3, width: 2, height: 8, background: i <= ci ? C.cyan : C.dim }} />
        ))}
      </div>
      <div style={{ position: 'absolute', left: side, top: top + 1.4 * u, font: `600 ${(portrait ? 1.8 : 1.4) * u}px ${MONO}`, color: C.dim2, letterSpacing: '0.08em' }}>
        <span style={{ color: C.cyan }}>{String(ci + 1).padStart(2, '0')}</span> / {String(doc.chapters.length).padStart(2, '0')} · {doc.chapters[ci]?.title}
      </div>
      {beat.caption && (
        <div style={{ position: 'absolute', left: 0, right: 0, bottom: (portrait ? 9 : 3.6) * u, display: 'flex', justifyContent: 'center' }}>
          <div style={{ maxWidth: portrait ? '86%' : '70%', textAlign: 'center', font: `500 ${(portrait ? 2.6 : 1.7) * u}px ${SANS}`,
            color: C.dim2, background: '#0B0E22cc', border: `1px solid ${C.border}`, borderRadius: 99, padding: `${0.7 * u}px ${2.2 * u}px`,
            lineHeight: 1.4, opacity: capP, transform: `translateY(${(1 - capP) * u}px)` }}>{beat.caption}</div>
        </div>
      )}
    </Fill>
  );
};

export const Explainer: React.FC<{ doc: Doc; width?: number; height?: number; fps?: number }> = (p) => {
  const cfg = useCompositionConfig();
  const W = p.width ?? cfg.width, H = p.height ?? cfg.height, fps = p.fps ?? cfg.fps;
  const base = Math.min(W, H) / 100, portrait = H > W;
  // landscape layouts are authored at 16:9 and 1.35x; narrower landscape (1:1) shrinks so nothing overflows
  const u = portrait ? base : 1.35 * base * Math.min(1, W / H / (16 / 9));
  const stage: Stage = { u, tu: portrait ? 1.3 * base : u, W, H, portrait, fps };
  const total = p.doc.beats.reduce((m, b) => Math.max(m, b.t + b.dur), 0);
  return (
    <S.Provider value={stage}>
      <Fill style={{ background: C.bgEdge, color: C.text, overflow: 'hidden', fontFamily: SANS }}>
        <Ambient />
        {p.doc.beats.map((b) => {
          const from = Math.round(b.t * fps), n = Math.round((b.t + b.dur) * fps) - from;
          return <Sequence key={b.id} from={from} durationInFrames={n}><BeatView b={b} n={n} /></Sequence>;
        })}
        <Chrome doc={p.doc} total={total} />
      </Fill>
    </S.Provider>
  );
};
