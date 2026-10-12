/**
 * Hero stage spotlight — armed under loader; visible sequence starts after loader is gone.
 */
(function () {
  var TRAVEL_MS = 820;
  var TITLE_HOLD_MS = 1350;
  var TITLE_HOLD_LITE_MS = 1000;
  var TITLE_HOLD_REDUCED_MS = 480;

  var baseSpot = { x: 0, y: 0, r: 140 };
  var wobbleOn = false;
  var wobbleRaf = 0;
  var wobbleSeed = Math.random() * 2000;
  var wobbleDim = null;

  var EASE = function (t) {
    return 1 - Math.pow(1 - t, 3);
  };

  function wait(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function measureEl(hero, el, padX, padY) {
    var er = el.getBoundingClientRect();
    if (!er.width && !er.height) return null;
    var px = padX != null ? padX : 40;
    var py = padY != null ? padY : 28;
    var w = er.width + px * 2;
    var h = er.height + py * 2;
    return {
      x: er.left + er.width / 2,
      y: er.top + er.height / 2,
      r: Math.max(w, h) * 0.54,
    };
  }

  function measureGroup(hero, nodes, pad) {
    var padV = pad != null ? pad : 22;
    var minL = Infinity;
    var minT = Infinity;
    var maxR = -Infinity;
    var maxB = -Infinity;
    var any = false;
    nodes.forEach(function (el) {
      if (!el) return;
      if (el.hidden) return;
      var er = el.getBoundingClientRect();
      if (!er.width && !er.height) return;
      any = true;
      minL = Math.min(minL, er.left);
      minT = Math.min(minT, er.top);
      maxR = Math.max(maxR, er.right);
      maxB = Math.max(maxB, er.bottom);
    });
    if (!any) return null;
    var w = maxR - minL + padV * 2;
    var h = maxB - minT + padV * 2;
    return {
      x: (minL + maxR) / 2,
      y: (minT + maxB) / 2,
      r: Math.max(w, h) * 0.52,
    };
  }

  function collectSpots(hero) {
    var title = hero.querySelector('.hero__title');
    var dateBlock = hero.querySelector('.hero__date-block');
    var capacity = document.getElementById('capacity-badge');
    var register = document.getElementById('hero-register-cta');

    var spots = [];
    var s1 = measureEl(hero, title, 56, 44);
    var s2 = dateBlock ? measureEl(hero, dateBlock, 28, 22) : null;
    var s3 = measureGroup(hero, [capacity, register], 18);
    if (s1) spots.push(s1);
    if (s2) spots.push(s2);
    if (s3) spots.push(s3);
    return spots;
  }

  function openingSpot(hero) {
    var w = window.innerWidth || hero.clientWidth || 360;
    var h = window.innerHeight || hero.clientHeight || 640;
    return {
      x: w * 0.5,
      y: h * 0.38,
      r: Math.max(w, h) * 0.48,
    };
  }

  function wobbleAmp(dim) {
    if (!dim) return 1;
    if (dim.classList.contains('is-reduced')) return 0.5;
    return 1;
  }

  function paintSpot(dim) {
    var ox = 0;
    var oy = 0;
    var dr = 0;
    if (wobbleOn) {
      var t = performance.now() + wobbleSeed;
      var amp = wobbleAmp(dim);
      ox = (Math.sin(t * 0.00112) * 2.4 + Math.sin(t * 0.00208) * 1.05) * amp;
      oy = (Math.cos(t * 0.00131) * 1.75 + Math.sin(t * 0.00088) * 1.15) * amp;
      dr = Math.sin(t * 0.00162) * 2.2 * amp;
    }
    dim.style.setProperty('--spot-x', baseSpot.x + ox + 'px');
    dim.style.setProperty('--spot-y', baseSpot.y + oy + 'px');
    dim.style.setProperty('--spot-r', baseSpot.r + dr + 'px');
  }

  function applySpot(dim, spot) {
    baseSpot.x = spot.x;
    baseSpot.y = spot.y;
    baseSpot.r = spot.r;
    paintSpot(dim);
  }

  function startHandheld(dim, reduceMotion) {
    if (reduceMotion || wobbleOn) return;
    wobbleDim = dim;
    wobbleOn = true;
    function loop() {
      if (!wobbleOn || !wobbleDim) return;
      paintSpot(wobbleDim);
      wobbleRaf = requestAnimationFrame(loop);
    }
    wobbleRaf = requestAnimationFrame(loop);
  }

  function stopHandheld() {
    wobbleOn = false;
    wobbleDim = null;
    if (wobbleRaf) {
      cancelAnimationFrame(wobbleRaf);
      wobbleRaf = 0;
    }
  }

  function tween(dim, from, to, ms, done) {
    if (ms <= 0) {
      applySpot(dim, to);
      if (done) done();
      return;
    }
    var t0 = performance.now();
    function frame(now) {
      var t = Math.min(1, (now - t0) / ms);
      var e = EASE(t);
      applySpot(dim, {
        x: from.x + (to.x - from.x) * e,
        y: from.y + (to.y - from.y) * e,
        r: from.r + (to.r - from.r) * e,
      });
      if (t < 1) requestAnimationFrame(frame);
      else if (done) done();
    }
    requestAnimationFrame(frame);
  }

  function prepareDim(dim, reduceMotion) {
    dim.hidden = false;
    dim.removeAttribute('hidden');
    dim.classList.remove('is-done', 'is-exit');
    dim.classList.add('is-active');
    document.documentElement.classList.add('wwh-spotlight-active');
    var touch =
      window.matchMedia('(hover: none) and (pointer: coarse)').matches ||
      document.documentElement.classList.contains('wwh-perf-lite') ||
      document.documentElement.classList.contains('wwh-touch');
    if (reduceMotion || touch) {
      dim.classList.add('is-reduced');
    }
    startHandheld(dim, reduceMotion);
  }

  function travelMs(reduceMotion) {
    if (reduceMotion) return 0;
    var lite = document.documentElement.classList.contains('wwh-perf-lite');
    return lite ? Math.round(TRAVEL_MS * 0.88) : TRAVEL_MS;
  }

  function titleHoldMs(reduceMotion) {
    if (reduceMotion) return TITLE_HOLD_REDUCED_MS;
    var lite = document.documentElement.classList.contains('wwh-perf-lite');
    return lite ? TITLE_HOLD_LITE_MS : TITLE_HOLD_MS;
  }

  /** Under loader: drift toward title while overlay still visible */
  function armUnderLoader(hero, dim, reduceMotion) {
    prepareDim(dim, reduceMotion);
    var spots = collectSpots(hero);
    if (!spots.length) return;
    var open = openingSpot(hero);
    var travel = travelMs(reduceMotion);
    applySpot(dim, open);
    if (spots[0] && travel > 0) {
      tween(dim, open, spots[0], travel, function () {});
    } else if (spots[0]) {
      applySpot(dim, spots[0]);
    }
  }

  /** After loader gone: lock on «ما اینجا بودیم», then date block, then capacity + CTA */
  function playVisibleSequence(hero, dim, reduceMotion) {
    var spots = collectSpots(hero);
    if (spots.length < 2) return Promise.resolve();

    var lite = document.documentElement.classList.contains('wwh-perf-lite');
    var legHolds = reduceMotion ? [520, 420] : lite ? [920, 780] : [1050, 900];
    var travel = travelMs(reduceMotion);

    applySpot(dim, spots[0]);

    var chain = wait(titleHoldMs(reduceMotion));

    for (var i = 0; i < spots.length - 1; i++) {
      (function (idx) {
        chain = chain.then(function () {
          return new Promise(function (resolve) {
            tween(dim, spots[idx], spots[idx + 1], travel, resolve);
          });
        });
        chain = chain.then(function () {
          return wait(legHolds[idx] != null ? legHolds[idx] : 400);
        });
      })(i);
    }

    return chain
      .then(function () {
        stopHandheld();
        dim.classList.remove('is-active');
        dim.classList.add('is-exit');
        return wait(reduceMotion ? 450 : 700);
      })
      .then(function () {
        dim.classList.remove('is-exit');
        dim.classList.add('is-done');
        dim.setAttribute('hidden', '');
        document.documentElement.classList.remove('wwh-spotlight-active');
      });
  }

  function init() {
    var hero = document.getElementById('hero');
    var dim = document.getElementById('hero-spotlight');
    if (!hero || !dim) return;

    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var armed = false;
    var loaderGone = false;
    var playing = false;

    function tryPlay() {
      if (playing || !armed || !loaderGone) return;
      playing = true;
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          playVisibleSequence(hero, dim, reduceMotion);
        });
      });
    }

    window.addEventListener(
      'wwh:loader-arm-spotlight',
      function () {
        if (armed) return;
        armed = true;
        armUnderLoader(hero, dim, reduceMotion);
      },
      { once: true }
    );

    window.addEventListener(
      'wwh:loader-done',
      function () {
        loaderGone = true;
        if (!armed) {
          armed = true;
          prepareDim(dim, reduceMotion);
          var spots = collectSpots(hero);
          if (spots[0]) applySpot(dim, spots[0]);
        }
        tryPlay();
      },
      { once: true }
    );

    if (window.__wwhLoaderDone) {
      loaderGone = true;
      armed = true;
      prepareDim(dim, reduceMotion);
      var spots = collectSpots(hero);
      if (spots[0]) applySpot(dim, spots[0]);
      tryPlay();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
