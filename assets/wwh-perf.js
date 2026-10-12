/**
 * Lite motion on low-end devices — keeps animations, reduces cost (blur layers, extra particles).
 */
(function () {
  'use strict';
  var root = document.documentElement;
  if (root.classList.contains('wwh-perf-lite')) return;

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) {
    root.classList.add('wwh-perf-lite');
    return;
  }

  var cores = typeof navigator.hardwareConcurrency === 'number' ? navigator.hardwareConcurrency : 8;
  var mem = typeof navigator.deviceMemory === 'number' ? navigator.deviceMemory : 8;
  var saveData = false;
  try {
    var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    saveData = !!(conn && conn.saveData);
  } catch (e) { /* ignore */ }

  var coarse = window.matchMedia('(hover: none) and (pointer: coarse)').matches;
  var narrow = window.matchMedia('(max-width: 480px)').matches;

  if (saveData || cores <= 4 || mem <= 4 || (coarse && narrow && (cores <= 6 || mem <= 6))) {
    root.classList.add('wwh-perf-lite');
  }

  if (coarse) {
    root.classList.add('wwh-touch');
  }
})();
