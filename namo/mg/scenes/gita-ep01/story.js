// Gita 1.1 — Dhritarashtra Uvacha
// Single source of truth for the timeline (seconds). Deterministic: every frame is render(t).
export const DUR = 60;
export const T = {
  open:      0.0,    // paper, ink drop
  dropFall:  0.6, dropHit: 1.1,
  titleIn:   2.2, titleOut: 6.2,
  hallIn:    6.4,    // hall blooms in
  thro:      10.0,   // throne appears
  king:      14.0,   // king seated
  hand:      18.0,   // hand on armrest
  sanjay:    22.0,   // sanjay appears
  eyes:      26.0,   // his eyes close-up
  visionA:   30.0, visionB: 31.2,  // battlefield blooms in the hall air
  field:     33.0,   // the plain at dawn
  armies:    38.0,   // two armies
  grass:     43.0,   // low angle through grass
  lean:      48.0,   // king leans forward
  chariot:   52.0,   // lone chariot at sunrise
  close:     55.0,   // king alone, long hall
  scrollA:   57.0,   // end: handscroll closes
};
export const VO = [
  { id: 'S1', t: 7.0,  sub: [6.9, 13.6],  text: 'धृतराष्ट्र उवाच' },
  { id: 'S2', t: 14.4, sub: [14.3, 21.4], text: 'धर्मक्षेत्रे कुरुक्षेत्रे' },
  { id: 'S3', t: 22.2, sub: [22.1, 29.4], text: 'समवेता युयुत्सवः' },
  { id: 'S4', t: 30.0, sub: [29.9, 37.4], text: 'मामकाः पाण्डवाश्चैव' },
  { id: 'S5', t: 38.2, sub: [38.1, 47.4], text: 'किमकुर्वत सञ्जय' },
];
