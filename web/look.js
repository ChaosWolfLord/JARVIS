// Picks the look before the page is painted, so it never flashes the wrong one. This is a plain script (not a module) loaded in the
// head: the page's security policy only allows scripts from this server, so it cannot be written inline.
(function () {
  var modern = true;
  try { modern = localStorage.getItem('jarvis.look') !== 'classic'; } catch (e) { /* storage blocked: the modern look is the default */ }
  document.documentElement.classList.toggle('modern', modern);
})();
