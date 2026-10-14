/**
 * Hero stage spotlight — armed under loader; visible sequence starts after loader is gone.
 *
 * Soft scroll-lock while the sequence runs so eager mobile scroll doesn't break the show,
 * with tap-to-skip on the overlay (user freedom). Targets remeasure live; unlock after.
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

  var session = {
    active: false,
    aborted: false,
    hero: null,
    dim: null,
    reduceMotion: false,
    scrollLocked: false,
    skipBound: false,
    flickerTimers: [],
    shutterLoopOn: false,
    /** 1 = hole open (reveal), 0 = hole filled (full black dim) */
    irisOpen: 1,
  };

  var EASE = function (t) {
    return 1 - Math.pow(1 - t, 3);
  };

  function wait(ms) {
    return new Promise(function (resolve) {
      var t0 = performance.now();
      function tick(now) {
        if (session.aborted) {
          resolve();
          return;
        }
        if (now - t0 >= ms) {
          resolve();
          return;
        }
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });
  }

  function clearFlickerTimers() {
    (session.flickerTimers || []).forEach(function (id) {
      window.clearTimeout(id);
    });
    session.flickerTimers = [];
  }

  function setIrisOpen(dim, open) {
    session.irisOpen = open ? 1 : 0;
    if (dim) {
      dim.classList.toggle('is-iris-closed', !open);
      paintSpot(dim);
    }
  }

  function stopFlicker(dim) {
    session.shutterLoopOn = false;
    clearFlickerTimers();
    session.irisOpen = 1;
    if (!dim) return;
    dim.classList.remove('is-iris-closed');
    paintSpot(dim);
  }

  function randMs(min, max) {
    return min + Math.random() * (max - min);
  }

  /** Closed iris — brief blink; mostly soft, rarely a heavier slap. */
  function shutterClosedMs() {
    var roll = Math.random();
    if (roll < 0.65) return randMs(28, 48);
    if (roll < 0.9) return randMs(48, 72);
    return randMs(72, 100);
  }

  /** Long open rests so the reveal stays readable; gaps stay uneven. */
  function shutterGapMs() {
    var roll = Math.random();
    if (roll < 0.45) return randMs(280, 520);
    if (roll < 0.8) return randMs(520, 900);
    return randMs(900, 1400);
  }

  /** Usually one click; rare soft double — never a machine-gun triple. */
  function appendShutterBurst(steps, endOpenMs) {
    var n = Math.random() < 0.18 ? 2 : 1;
    var i;
    for (i = 0; i < n; i++) {
      steps.push({ closed: true, ms: shutterClosedMs() });
      if (i < n - 1) {
        steps.push({ closed: false, ms: randMs(40, 70) });
      } else {
        steps.push({ closed: false, ms: endOpenMs });
      }
    }
  }

  function scheduleFlicker(ms, fn) {
    var id = window.setTimeout(fn, ms);
    session.flickerTimers.push(id);
  }

  /**
   * Soft continuous shutter for the whole spotlight life — including travel.
   * Sparse + random so the hole stays readable (showcase, not strobe).
   */
  function startContinuousShutter(dim) {
    if (!dim || session.reduceMotion || session.shutterLoopOn) return;
    session.shutterLoopOn = true;

    function alive() {
      return session.shutterLoopOn && session.active && !session.aborted;
    }

    function playSteps(steps, onDone) {
      var i = 0;
      function next() {
        if (!alive()) {
          setIrisOpen(dim, true);
          return;
        }
        if (i >= steps.length) {
          onDone();
          return;
        }
        var step = steps[i++];
        setIrisOpen(dim, !step.closed);
        scheduleFlicker(Math.max(1, step.ms || 1), next);
      }
      next();
    }

    function loop() {
      if (!alive()) {
        setIrisOpen(dim, true);
        return;
      }
      var steps = [];
      appendShutterBurst(steps, shutterGapMs());
      playSteps(steps, loop);
    }

    /* Settle on the hole first, then a gentle first blink */
    scheduleFlicker(randMs(220, 480), loop);
  }

  function measureEl(hero, el, padX, padY) {
    if (!el) return null;
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
    var open = session.irisOpen == null ? 1 : session.irisOpen;
    var r = Math.max(0, (baseSpot.r + dr) * open);
    dim.style.setProperty('--spot-x', baseSpot.x + ox + 'px');
    dim.style.setProperty('--spot-y', baseSpot.y + oy + 'px');
    dim.style.setProperty('--spot-r', r + 'px');
  }

  function applySpot(dim, spot) {
    if (!spot) return;
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

  function preventScrollEvent(e) {
    if (!session.scrollLocked) return;
    e.preventDefault();
  }

  function lockScroll() {
    if (session.scrollLocked) return;
    session.scrollLocked = true;
    document.documentElement.classList.add('wwh-spotlight-scroll-lock');
    window.scrollTo(0, 0);
    window.addEventListener('wheel', preventScrollEvent, { passive: false });
    window.addEventListener('touchmove', preventScrollEvent, { passive: false });
  }

  function unlockScroll() {
    if (!session.scrollLocked) return;
    session.scrollLocked = false;
    document.documentElement.classList.remove('wwh-spotlight-scroll-lock');
    window.removeEventListener('wheel', preventScrollEvent);
    window.removeEventListener('touchmove', preventScrollEvent);
  }

  function bindSkipTap(dim) {
    if (!dim || session.skipBound) return;
    session.skipBound = true;
    dim.style.cursor = 'pointer';
    dim.setAttribute('role', 'button');
    dim.setAttribute('tabindex', '0');
    dim.setAttribute('aria-label', 'رد کردن معرفی');
    function skip() {
      if (!session.active || session.aborted) return;
      session.aborted = true;
      finishSpotlight(true);
    }
    dim.addEventListener('click', skip);
    dim.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Escape') {
        e.preventDefault();
        skip();
      }
    });
  }

  function finishSpotlight(instant) {
    var dim = session.dim;
    unlockScroll();
    session.active = false;
    stopHandheld();
    stopFlicker(dim);
    if (dim) {
      dim.removeAttribute('role');
      dim.removeAttribute('tabindex');
      dim.removeAttribute('aria-label');
      dim.style.cursor = '';
      dim.classList.remove('is-active');
    }
    if (!dim) {
      document.documentElement.classList.remove('wwh-spotlight-active');
      return Promise.resolve();
    }
    if (instant) {
      dim.classList.remove('is-exit');
      dim.classList.add('is-done');
      dim.setAttribute('hidden', '');
      document.documentElement.classList.remove('wwh-spotlight-active');
      return Promise.resolve();
    }
    dim.classList.add('is-exit');
    return wait(session.reduceMotion ? 450 : 700).then(function () {
      dim.classList.remove('is-exit');
      dim.classList.add('is-done');
      dim.setAttribute('hidden', '');
      document.documentElement.classList.remove('wwh-spotlight-active');
    });
  }

  /** Tween while remeasuring the destination each frame (survives small layout shifts). */
  function tweenToIndex(hero, dim, toIdx, ms) {
    return new Promise(function (resolve) {
      if (session.aborted) {
        resolve();
        return;
      }
      var start = {
        x: baseSpot.x,
        y: baseSpot.y,
        r: baseSpot.r,
      };
      if (ms <= 0) {
        var spots0 = collectSpots(hero);
        if (spots0[toIdx]) applySpot(dim, spots0[toIdx]);
        resolve();
        return;
      }
      var t0 = performance.now();
      function frame(now) {
        if (session.aborted) {
          resolve();
          return;
        }
        var t = Math.min(1, (now - t0) / ms);
        var e = EASE(t);
        var live = collectSpots(hero);
        var end = live[toIdx] || start;
        applySpot(dim, {
          x: start.x + (end.x - start.x) * e,
          y: start.y + (end.y - start.y) * e,
          r: start.r + (end.r - start.r) * e,
        });
        if (t < 1) requestAnimationFrame(frame);
        else resolve();
      }
      requestAnimationFrame(frame);
    });
  }

  /** Hold on a spot while remeasuring so address-bar / minor shifts stay aligned. */
  function holdOnIndex(hero, dim, idx, ms) {
    return new Promise(function (resolve) {
      var t0 = performance.now();
      function tick(now) {
        if (session.aborted) {
          resolve();
          return;
        }
        var spots = collectSpots(hero);
        if (spots[idx]) applySpot(dim, spots[idx]);
        if (now - t0 >= ms) {
          resolve();
          return;
        }
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });
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

  function beginSession(hero, dim, reduceMotion) {
    session.hero = hero;
    session.dim = dim;
    session.reduceMotion = reduceMotion;
    session.aborted = false;
    session.active = true;
    bindSkipTap(dim);
    lockScroll();
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
    beginSession(hero, dim, reduceMotion);
    prepareDim(dim, reduceMotion);
    var spots = collectSpots(hero);
    if (!spots.length) return;
    var open = openingSpot(hero);
    var travel = travelMs(reduceMotion);
    applySpot(dim, open);
    startContinuousShutter(dim);
    if (spots[0] && travel > 0) {
      tweenToIndex(hero, dim, 0, travel);
    } else if (spots[0]) {
      applySpot(dim, spots[0]);
    }
  }

  /** After loader gone: lock on «ما اینجا بودیم», then date block, then capacity + CTA */
  function playVisibleSequence(hero, dim, reduceMotion) {
    beginSession(hero, dim, reduceMotion);
    var spots = collectSpots(hero);
    if (spots.length < 2) {
      return finishSpotlight(true);
    }

    var lite = document.documentElement.classList.contains('wwh-perf-lite');
    var legHolds = reduceMotion ? [520, 420] : lite ? [920, 780] : [1050, 900];
    var travel = travelMs(reduceMotion);

    applySpot(dim, spots[0]);
    startContinuousShutter(dim);

    var chain = holdOnIndex(hero, dim, 0, titleHoldMs(reduceMotion));

    for (var i = 0; i < spots.length - 1; i++) {
      (function (idx) {
        chain = chain.then(function () {
          if (session.aborted) return;
          return tweenToIndex(hero, dim, idx + 1, travel);
        });
        chain = chain.then(function () {
          if (session.aborted) return;
          return holdOnIndex(hero, dim, idx + 1, legHolds[idx] != null ? legHolds[idx] : 400);
        });
      })(i);
    }

    return chain.then(function () {
      if (session.aborted) return;
      return finishSpotlight(false);
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
          beginSession(hero, dim, reduceMotion);
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
      beginSession(hero, dim, reduceMotion);
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
