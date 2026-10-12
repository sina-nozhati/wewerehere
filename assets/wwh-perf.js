/**
 * Lite motion on low-end devices — keeps animations, reduces cost (blur layers, extra particles).
 * Also injects Google Fonts (smaller bundle on touch; decorative families after load).
 */
(function () {
  'use strict';
  var root = document.documentElement;
  var coarse = window.matchMedia('(hover: none) and (pointer: coarse)').matches;
  var narrow = window.matchMedia('(max-width: 480px)').matches;

  var FONTS_DESKTOP =
    'https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700;900&family=JetBrains+Mono:wght@400;600;700&family=Vazirmatn:wght@400;500;600;700;800&display=swap';
  var FONTS_TOUCH_PRIMARY =
    'https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700;800;900&display=swap';
  var FONTS_TOUCH_EXTRA =
    'https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=JetBrains+Mono:wght@400;600&display=swap';

  function injectFonts() {
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = coarse ? FONTS_TOUCH_PRIMARY : FONTS_DESKTOP;
    document.head.appendChild(link);
    if (coarse) {
      window.addEventListener(
        'load',
        function () {
          var extra = document.createElement('link');
          extra.rel = 'stylesheet';
          extra.href = FONTS_TOUCH_EXTRA;
          document.head.appendChild(extra);
        },
        { once: true }
      );
    }
  }

  injectFonts();

  if (root.classList.contains('wwh-perf-lite')) {
    if (coarse) root.classList.add('wwh-touch');
    root.classList.add('wwh-loader-simple');
    return;
  }

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) {
    root.classList.add('wwh-perf-lite');
    if (coarse) root.classList.add('wwh-touch');
    return;
  }

  var cores = typeof navigator.hardwareConcurrency === 'number' ? navigator.hardwareConcurrency : 8;
  var mem = typeof navigator.deviceMemory === 'number' ? navigator.deviceMemory : 8;
  var saveData = false;
  try {
    var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    saveData = !!(conn && conn.saveData);
  } catch (e) {
    /* ignore */
  }

  if (saveData || cores <= 4 || mem <= 4 || (coarse && narrow && (cores <= 6 || mem <= 6))) {
    root.classList.add('wwh-perf-lite');
  }

  if (coarse) {
    root.classList.add('wwh-touch');
    root.classList.add('wwh-loader-simple');
  } else if (root.classList.contains('wwh-perf-lite')) {
    root.classList.add('wwh-loader-simple');
  }
})();
