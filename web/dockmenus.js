// The two small menus above the bottom bar: Colour (pen colour and thickness) and More (the buttons that are used now and then, each with a
// line saying what it does). Only one menu is open at a time (the Status and Cards menus close themselves when you click elsewhere, which
// includes these buttons), a click outside or Escape closes them, and choosing something in More closes it.

import { fitMenu } from './menufit.js';

export function dockMenus(pairs) {
  const setOpen = (p, open) => {
    p.menu.hidden = !open;
    p.button.setAttribute('aria-expanded', String(open));
    if (open) fitMenu(p.menu);
  };
  const closeAll = (except = null) => pairs.forEach((p) => { if (p !== except && !p.menu.hidden) setOpen(p, false); });

  for (const p of pairs) {
    p.button.addEventListener('click', () => {
      const open = p.menu.hidden;
      closeAll(p);
      setOpen(p, open);
    });
    if (p.closeOnChoice) p.menu.addEventListener('click', (e) => { if (e.target.closest('.menu-row')) setOpen(p, false); });
  }
  document.addEventListener('click', (e) => {
    for (const p of pairs) if (!p.menu.hidden && !p.menu.contains(e.target) && !p.button.contains(e.target)) setOpen(p, false);
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAll(); });
  window.addEventListener('resize', () => pairs.forEach((p) => fitMenu(p.menu)));
  return { closeAll };
}

/** Tells the bar how much room it has (the chat panel beside the board narrows it), so it can shrink its buttons before they collide with the orb. */
export function watchDockSize(bar) {
  const set = (w) => { bar.dataset.size = w < 790 ? 'tight' : w < 1010 ? 'compact' : 'roomy'; };
  set(bar.clientWidth);
  new ResizeObserver(([e]) => set(e.contentRect.width + 28)).observe(bar);
}
