// The look of JARVIS: "modern" (calm glass, soft colour) or "classic" (the original neon-on-black). Everything made of CSS follows the
// variables in style.css and modern.css; this file is for the pieces drawn on canvases (the orb, the hologram card, the start-up
// sequence, the board's ink), which cannot read CSS and so ask for their colours here.

export const LOOKS = ['modern', 'classic'];

const INK = {
  classic: { cyan: '#00e5ff', white: '#e8f4ff', amber: '#ffb300', green: '#5cff8a', red: '#ff5252' },
  modern: { cyan: '#7abeff', white: '#f2f5fb', amber: '#ffc46b', green: '#6ee7b0', red: '#ff7a85' },
};

const ACCENT = { classic: [0, 229, 255], modern: [122, 190, 255] };
const ACCENT2 = { classic: [61, 123, 255], modern: [176, 142, 255] };

/** The look that is chosen right now. */
export function currentLook() {
  try { return localStorage.getItem('jarvis.look') === 'classic' ? 'classic' : 'modern'; } catch { return 'modern'; }
}

export const isModern = () => currentLook() === 'modern';

/** Switches the look (or just re-applies the stored one when called with nothing) and tells the canvases to repaint in it. */
export function applyLook(value) {
  if (LOOKS.includes(value)) { try { localStorage.setItem('jarvis.look', value); } catch { /* not saved: the page still switches */ } }
  const look = currentLook();
  if (typeof document !== 'undefined') document.documentElement.classList.toggle('modern', look === 'modern');
  if (typeof window !== 'undefined' && window.dispatchEvent && typeof Event === 'function') window.dispatchEvent(new Event('jarvis-look'));
  return look;
}

export const inkPalette = (look = currentLook()) => INK[look] || INK.modern;
export const accent = (look = currentLook()) => ACCENT[look] || ACCENT.modern;
export const accent2 = (look = currentLook()) => ACCENT2[look] || ACCENT2.modern;

/** "r, g, b" for use inside rgba(). */
export const rgbText = (c) => c.join(', ');

/** Mixes a colour toward white (amount 0..1). */
export const lighten = (c, amount) => c.map((v) => Math.round(v + (255 - v) * amount));

const hex = (c) => `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`;

/** Everything the orb draws with, for the current look. */
export function orbPalette(look = currentLook()) {
  if (look === 'classic') {
    return {
      modern: false, halo: '150, 215, 255', dots: '190, 230, 255', ripple: '110, 205, 255', glow: '50, 165, 255', inner: '215, 245, 255', name: '120, 200, 255',
      ring: ['#8fe0ff', '#2e9bff', '#1b63ff'], bar0: [150, 215, 255], bar1: [240, 245, 255], centre: 'rgba(1, 5, 11, 0.97)',
    };
  }
  const a = ACCENT.modern, b = ACCENT2.modern;
  return {
    modern: true, halo: rgbText(lighten(a, 0.35)), dots: rgbText(lighten(a, 0.5)), ripple: rgbText(a), glow: rgbText(a), inner: rgbText(lighten(a, 0.7)), name: rgbText(a),
    ring: [hex(lighten(a, 0.45)), hex(a), hex(b)], bar0: lighten(a, 0.1), bar1: lighten(a, 0.75), centre: 'rgba(9, 12, 21, 0.94)',
  };
}

/** The accent used by the hologram card and the start-up sequence: "r, g, b" plus a few lighter tints. */
export function canvasPalette(look = currentLook()) {
  const a = accent(look);
  return {
    rgb: rgbText(a), rgb2: rgbText(accent2(look)), arc: look === 'classic' ? '0, 190, 255' : rgbText(accent2(look)), bright: rgbText(lighten(a, 0.55)), pale: rgbText(lighten(a, 0.75)), hex: hex(a), hexBright: hex(lighten(a, 0.5)),
    text: look === 'classic' ? 'rgba(160, 220, 235, 0.8)' : 'rgba(205, 214, 232, 0.8)',
    series: look === 'classic'
      ? ['#00e5ff', '#4d8dff', '#5cff8a', '#ffb300', '#c77dff', '#ff6fb5', '#ff7a59', '#9be7ff']
      : ['#7abeff', '#b08eff', '#6ee7b0', '#ffc46b', '#ff8fb8', '#ff9a7a', '#8fe3ff', '#c9b8ff'],
  };
}
