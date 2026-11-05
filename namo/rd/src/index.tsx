import React from 'react';
import { setRootComponent, Composition, holdRender, releaseRender } from '@rendiv/core';
import '@fontsource/inter/500.css';
import '@fontsource/inter/800.css';
import '@fontsource/noto-sans-devanagari/500.css';
import '@fontsource/noto-sans-devanagari/700.css';
import '@fontsource/noto-serif-devanagari/600.css';
import '@fontsource/jetbrains-mono/600.css';
import '@fontsource/jetbrains-mono/800.css';
import { Explainer, type Doc } from './Explainer';
import json from '../beats/gita-1-1.json';

// studio/preview default only; renders pass the job's beats as inputProps (render.mjs)
const doc = json as unknown as Doc; // JSON imports widen literal unions (type: string)

// no frame is captured before every face (and its Devanagari subset) is loaded
const fonts = ['500 20px Inter', '800 20px Inter', '500 20px "Noto Sans Devanagari"', '700 20px "Noto Sans Devanagari"',
  '600 20px "Noto Serif Devanagari"', '600 20px "JetBrains Mono"', '800 20px "JetBrains Mono"'];
const hold = holdRender('fonts');
Promise.all(fonts.map((f) => document.fonts.load(f, 'कृष्ण Aa 0123 ॥ ◆'))).then(() => document.fonts.ready)
  .then(() => releaseRender(hold));
const seconds = doc.beats.reduce((m, b) => Math.max(m, b.t + b.dur), 0);

setRootComponent(() => (
  <Composition id="Explainer" component={Explainer} durationInFrames={seconds * 30} fps={30} width={1920} height={1080}
    defaultProps={{ doc }} />
));
