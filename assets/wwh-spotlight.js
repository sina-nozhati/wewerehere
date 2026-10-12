/**
 * Hero stage spotlight — armed before loader fade; first target ready when overlay lifts.
 */
(function () {
  var TRAVEL_MS = 820;

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
    var tagline = document.getElementById('hero-jalali-tagline');
    var capacity = document.getElementById('capacity-badge');
    var register = document.getElementById('hero-register-cta');

    var spots = [];
    var s1 = measureEl(hero, title, 52, 40);
    var s2 = measureEl(hero, tagline, 48, 36);
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

  function applySpot(dim, spot) {
    dim.style.setProperty('--spot-x', spot.x + 'px');
    dim.style.setProperty('--spot-y', spot.y + 'px');
    dim.style.setProperty('--spot-r', spot.r + 'px');
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
  }

  function runSequence(hero, dim, reduceMotion, opts) {
    opts = opts || {};
    var spots = collectSpots(hero);
    if (spots.length < 2) return Promise.resolve();

    var lite = document.documentElement.classList.contains('wwh-perf-lite');
    var holds = reduceMotion ? [500, 480, 320] : lite ? [820, 780, 320] : [1100, 1050, 420];
    var travel = reduceMotion ? 0 : lite ? Math.round(TRAVEL_MS * 0.85) : TRAVEL_MS;

    prepareDim(dim, reduceMotion);

    var chain;
    if (opts.skipOpening) {
      applySpot(dim, spots[0]);
      chain = wait(holds[0]);
    } else {
      var open = openingSpot(hero);
      applySpot(dim, open);
      chain = new Promise(function (resolve) {
        tween(dim, open, spots[0], travel, resolve);
      }).then(function () {
        return wait(holds[0]);
      });
    }

    for (var i = 0; i < spots.length - 1; i++) {
      (function (idx) {
        chain = chain.then(function () {
          return new Promise(function (resolve) {
            tween(dim, spots[idx], spots[idx + 1], travel, resolve);
          });
        });
        chain = chain.then(function () {
          return wait(holds[idx + 1] != null ? holds[idx + 1] : 400);
        });
      })(i);
    }

    return chain
      .then(function () {
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
    var started = false;

    function kick(opts) {
      if (started) return;
      started = true;
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          runSequence(hero, dim, reduceMotion, opts);
        });
      });
    }

    window.addEventListener(
      'wwh:loader-arm-spotlight',
      function () {
        kick({ skipOpening: false });
      },
      { once: true }
    );

    function fallbackStart() {
      kick({ skipOpening: true });
    }

    if (window.__wwhLoaderDone) {
      fallbackStart();
    } else {
      window.addEventListener('wwh:loader-done', fallbackStart, { once: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
