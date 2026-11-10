// The status menu and the widgets menu open upward from the dock. With many sections they can be taller than the room above the
// dock, which cut off their top on a small screen. This limits a menu's height to the room that is really there; the menu then
// scrolls inside itself.

const GAP = 14;      // the menu sits this far above the dock (see style.css)
const AIR = 12;      // and keeps this much clear at the top of the screen

export function fitMenu(menu) {
  const anchor = menu?.offsetParent;
  if (!anchor || menu.hidden) return;
  const box = anchor.getBoundingClientRect();
  const scale = anchor.offsetHeight ? box.height / anchor.offsetHeight : 1;      // the page can be scaled ("fit to wall")
  const room = box.top / (scale || 1) - GAP - AIR;
  menu.style.maxHeight = `${Math.max(160, Math.floor(room))}px`;
}

// A window that gets resized while a menu is open needs the menu re-fitted.
window.addEventListener('resize', () => document.querySelectorAll('#widget-menu').forEach((m) => fitMenu(m)));
