/**
 * Two fish — smooth JS steering (no position keyframes), optional random seek & collide.
 */
(function () {
  var layer = document.querySelector('.wwh-fish-layer');
  if (!layer) return;

  var fishEls = Array.prototype.slice.call(layer.querySelectorAll('.fish'));
  if (fishEls.length < 2) return;

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var meetCooldownUntil = 0;
  var loopRaf = 0;
  var margin = 170;
  var lastTick = 0;

  function rand(min, max) {
    return min + Math.random() * (max - min);
  }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function loadArtwork() {
    return fetch('/mahi.svg')
      .then(function (r) {
        return r.ok ? r.text() : Promise.reject();
      })
      .then(function (svg) {
        fishEls.forEach(function (fish) {
          var inner = fish.querySelector('.fish__inner');
          if (inner) inner.innerHTML = svg;
        });
      })
      .catch(function () {
        var fallback =
          '<img src="/mahi.svg" width="72" height="103" alt="" decoding="async" />';
        fishEls.forEach(function (fish) {
          var inner = fish.querySelector('.fish__inner');
          if (inner) inner.innerHTML = fallback;
        });
      });
  }

  function otherSwimmingFish(fish) {
    for (var i = 0; i < fishEls.length; i++) {
      var f = fishEls[i];
      if (f !== fish && f._swimming && f._motion) return f;
    }
    return null;
  }

  function makeWaypoints(fish, h, w, forceLtr, avoidY) {
    var ltr = forceLtr != null ? !!forceLtr : Math.random() < 0.5;
    var startX = ltr ? w + margin : -margin;
    var endX = ltr ? -margin : w + margin;

    /* Fresh lane every swim — avoid clustering with the mate */
    var yMin = h * 0.12;
    var yMax = h * 0.86;
    var y = rand(yMin, yMax);
    if (avoidY != null) {
      var tries = 0;
      while (Math.abs(y - avoidY) < h * 0.22 && tries < 12) {
        y = rand(yMin, yMax);
        tries += 1;
      }
    }
    fish._laneY = y;

    var count = 5 + Math.floor(Math.random() * 4);
    var pts = [];
    for (var i = 0; i < count; i++) {
      var t = i / (count - 1);
      var x = startX + (endX - startX) * t + rand(-w * 0.04, w * 0.04);
      if (i > 0) y += rand(-h * 0.06, h * 0.06);
      y = clamp(y, yMin, yMax);
      pts.push({ x: x, y: y });
    }
    return { points: pts, ltr: ltr, wp: 0 };
  }

  function initFishMotion(fish) {
    var h = window.innerHeight;
    var w = window.innerWidth;
    var width = rand(58, 96);
    var baseOpacity = rand(0.36, 0.5).toFixed(2);
    var mate = otherSwimmingFish(fish);
    var forceLtr = null;
    var avoidY = null;
    if (mate && mate._motion && mate._motion.path) {
      /* Opposite entry side + different vertical lane so they don't twin */
      forceLtr = !mate._motion.path.ltr;
      avoidY = mate._motion.y;
    } else if (fish._lastLtr != null && Math.random() < 0.65) {
      forceLtr = !fish._lastLtr;
    }
    var path = makeWaypoints(fish, h, w, forceLtr, avoidY);
    fish._lastLtr = path.ltr;
    var p0 = path.points[0];

    fish.style.width = width.toFixed(0) + 'px';
    fish.style.setProperty('--fish-opacity', baseOpacity);
    fish.style.setProperty('--wobble-dur', rand(1.5, 2.6).toFixed(2) + 's');
    fish._motion = {
      x: p0.x,
      y: p0.y,
      vx: 0,
      vy: 0,
      path: path,
      width: width,
      maxSpeed: rand(38, 58),
      maxAccel: rand(42, 72),
      wobbleSeed: rand(100, 380),
      seekMate: null,
      seekUntil: 0,
      seekChecked: false,
      nextInvite: performance.now() + rand(4500, 11000),
      baseOpacity: baseOpacity,
      boldUntil: 0,
      nextBold: performance.now() + rand(3500, 9000),
      pulseScale: 1,
      boldOpacity: baseOpacity,
    };
    updateFacing(fish, path.ltr ? -1 : 1);
    setTransform(fish, p0.x - width / 2, p0.y - width * 0.55, 1);
  }

  function updateFacing(fish, vx) {
    var left = vx < 0;
    fish.classList.toggle('fish--face-left', left);
    fish.classList.toggle('fish--face-right', !left);
  }

  function setTransform(fish, x, y, scale) {
    fish.style.transform =
      'translate3d(' + x.toFixed(2) + 'px,' + y.toFixed(2) + 'px,0) scale(' + (scale || 1).toFixed(3) + ')';
    var m = fish._motion;
    var hw = m ? m.width / 2 : (fish.offsetWidth || 50) / 2;
    var hh = m ? m.width * 0.55 : hw * 1.1;
    fish._pos = { x: x + hw, y: y + hh };
  }

  function stopSwim(fish) {
    if (fish._timer) {
      clearTimeout(fish._timer);
      fish._timer = 0;
    }
    fish._swimming = false;
    fish._motion = null;
    fish.classList.remove(
      'is-swimming',
      'fish--flinch',
      'fish--glow',
      'fish--invite',
      'fish--bold',
      'fish--hint'
    );
    fish.style.opacity = '0';
  }

  function runSwim(fish) {
    if (reduceMotion || fish._swimming) return;
    stopSwim(fish);
    initFishMotion(fish);
    fish._swimming = true;
    fish.classList.add('is-swimming');
    fish.style.opacity = fish.style.getPropertyValue('--fish-opacity') || '0.36';
  }

  function scheduleNext(fish) {
    /* Short gap so at least one fish is usually on screen while scrolling */
    fish._timer = window.setTimeout(function () {
      runSwim(fish);
    }, rand(350, 1600));
  }

  function steerToward(m, tx, ty, speedMul) {
    var dx = tx - m.x;
    var dy = ty - m.y;
    var dist = Math.hypot(dx, dy) || 1;
    var desiredVx = (dx / dist) * m.maxSpeed * (speedMul || 1);
    var desiredVy = (dy / dist) * m.maxSpeed * (speedMul || 1);
    var ax = desiredVx - m.vx;
    var ay = desiredVy - m.vy;
    var aLen = Math.hypot(ax, ay) || 1;
    var cap = m.maxAccel;
    if (aLen > cap) {
      ax = (ax / aLen) * cap;
      ay = (ay / aLen) * cap;
    }
    m.vx += ax;
    m.vy += ay;
    var vLen = Math.hypot(m.vx, m.vy) || 1;
    var maxV = m.maxSpeed * (speedMul || 1);
    if (vLen > maxV) {
      m.vx = (m.vx / vLen) * maxV;
      m.vy = (m.vy / vLen) * maxV;
    }
  }

  function showClickHint(fish) {
    var hint = fish.querySelector('.fish__hint');
    if (!hint) {
      hint = document.createElement('span');
      hint.className = 'fish__hint';
      hint.setAttribute('aria-hidden', 'true');
      hint.textContent = 'روی من کلیک کن';
      fish.insertBefore(hint, fish.firstChild);
    }
    fish.classList.add('fish--hint');
    window.clearTimeout(fish._hintTimer);
    fish._hintTimer = window.setTimeout(function () {
      fish.classList.remove('fish--hint');
    }, 3200);
  }

  function inviteGlance(fish, withHint) {
    if (fish.classList.contains('fish--glow') || fish.classList.contains('fish--flinch')) return;
    fish.classList.add('fish--invite');
    if (fish._pos) spawnRipple(fish._pos.x, fish._pos.y, true);
    if (withHint) showClickHint(fish);
    window.setTimeout(function () {
      fish.classList.remove('fish--invite');
    }, 1400);
  }

  function tickBoldPulse(fish, m, now) {
    if (now < m.boldUntil) {
      fish.classList.add('fish--bold');
      fish.style.opacity = m.boldOpacity;
      return;
    }
    fish.classList.remove('fish--bold');
    fish.style.opacity = m.baseOpacity;
    if (now > m.nextBold) {
      m.nextBold = now + rand(7500, 19000);
      if (Math.random() < 0.5) {
        m.boldUntil = now + rand(2400, 4800);
        m.pulseScale = rand(1.07, 1.15);
        m.boldOpacity = rand(0.55, 0.74).toFixed(2);
        inviteGlance(fish, Math.random() < 0.42);
      }
    }
  }

  function updateFish(fish, dt, now) {
    var m = fish._motion;
    if (!m || !fish._swimming) return;

    var path = m.path;
    var target = path.points[path.wp];
    var speedMul = 1;

    if (m.seekMate && m.seekMate._swimming && now < m.seekUntil) {
      var mate = m.seekMate._motion;
      if (mate) {
        target = { x: mate.x, y: mate.y };
        speedMul = m.seekSpeedMul || 1.12;
      }
    } else if (m.seekMate) {
      m.seekMate = null;
      m.seekUntil = 0;
    }

    steerToward(m, target.x, target.y, speedMul);
    m.x += m.vx * dt;
    m.y += m.vy * dt;

    var toWp = Math.hypot(target.x - m.x, target.y - m.y);
    if (toWp < 42 && path.wp < path.points.length - 1) {
      path.wp += 1;
    }

    var w = window.innerWidth;
    var h = window.innerHeight;
    var half = m.width * 0.85;
    var fullyOut =
      m.x < -half - 30 || m.x > w + half + 30 || m.y < -half - 30 || m.y > h + half + 30;
    var pastEnd = path.ltr ? m.x < -half - 30 : m.x > w + half + 30;

    /* Leave only after fully outside the viewport, and only through the far side. */
    if (path.wp >= path.points.length - 1 && fullyOut && pastEnd) {
      stopSwim(fish);
      scheduleNext(fish);
      return;
    }

    /* Subtle "notice me" cue at random times — no text, just a soft glow + ring. */
    if (now > m.nextInvite && m.x > 60 && m.x < w - 60 && m.y > 60 && m.y < h - 60) {
      m.nextInvite = now + rand(6000, 17000);
      inviteGlance(fish, Math.random() < 0.38);
    }

    tickBoldPulse(fish, m, now);

    var wobble = Math.sin(now / (200 + m.wobbleSeed)) * 1.6;
    var scale =
      (0.96 + Math.sin(now / 1100) * 0.03) * (now < m.boldUntil ? m.pulseScale : 1);
    setTransform(fish, m.x - m.width / 2, m.y - m.width * 0.55 + wobble, scale);
    if (Math.abs(m.vx) > 0.4) updateFacing(fish, m.vx);
  }

  function tryRandomSeek(a, b, now) {
    if (now < meetCooldownUntil) return;
    if (a._seekingRoll || b._seekingRoll) return;
    var ma = a._motion;
    var mb = b._motion;
    if (!ma || !mb) return;

    var dist = Math.hypot(ma.x - mb.x, ma.y - mb.y);
    if (dist > 340 || dist < 70) return;

    var w = window.innerWidth;
    if (ma.x < -40 || ma.x > w + 40 || mb.x < -40 || mb.x > w + 40) return;

    a._seekingRoll = true;
    b._seekingRoll = true;

    if (Math.random() > 0.26) {
      window.setTimeout(function () {
        a._seekingRoll = false;
        b._seekingRoll = false;
      }, rand(2000, 5000));
      return;
    }

    var until = now + rand(2800, 6200);
    ma.seekMate = b;
    mb.seekMate = a;
    ma.seekUntil = until;
    mb.seekUntil = until;
    ma.seekSpeedMul = rand(1.06, 1.16);
    mb.seekSpeedMul = rand(1.06, 1.16);
    ma.maxSpeed *= rand(1.04, 1.12);
    mb.maxSpeed *= rand(1.04, 1.12);

    window.setTimeout(function () {
      if (ma.seekMate === b) {
        ma.seekMate = null;
        mb.seekMate = null;
      }
      a._seekingRoll = false;
      b._seekingRoll = false;
    }, until - now + 200);
  }

  function resolveCollision(a, b, now) {
    if (now < meetCooldownUntil) return;
    var ma = a._motion;
    var mb = b._motion;
    if (!ma || !mb) return;

    var dist = Math.hypot(ma.x - mb.x, ma.y - mb.y);
    if (dist >= 46) return;

    meetCooldownUntil = now + rand(2200, 3600);
    var cx = (ma.x + mb.x) / 2;
    var cy = (ma.y + mb.y) / 2;

    ma.seekMate = null;
    mb.seekMate = null;
    ma.seekUntil = 0;
    mb.seekUntil = 0;
    a._seekingRoll = false;
    b._seekingRoll = false;

    var nx = (ma.x - mb.x) / (dist || 1);
    var ny = (ma.y - mb.y) / (dist || 1);
    var push = rand(55, 95);
    ma.vx += nx * push;
    ma.vy += ny * push;
    mb.vx -= nx * push;
    mb.vy -= ny * push;

    onMeet(a, b, cx, cy);
  }

  function spawnRipple(x, y, soft) {
    var ripple = document.createElement('span');
    ripple.className = 'fish-meet-ripple' + (soft ? ' fish-meet-ripple--soft' : '');
    ripple.style.left = x + 'px';
    ripple.style.top = y + 'px';
    layer.appendChild(ripple);
    ripple.addEventListener('animationend', function () { ripple.remove(); }, { once: true });
  }

  function spawnSparks(x, y) {
    var n = 4 + Math.floor(Math.random() * 5);
    for (var i = 0; i < n; i++) {
      var s = document.createElement('span');
      s.className = 'fish-meet-spark';
      s.style.left = x + rand(-10, 10) + 'px';
      s.style.top = y + rand(-8, 8) + 'px';
      s.style.setProperty('--dx', rand(-32, 32).toFixed(0) + 'px');
      s.style.setProperty('--dy', rand(-42, -10).toFixed(0) + 'px');
      layer.appendChild(s);
      s.addEventListener('animationend', function () { s.remove(); }, { once: true });
    }
  }

  function burstAt(x, y, big) {
    spawnRipple(x, y);
    spawnSparks(x, y);
    if (big) spawnRipple(x + rand(-20, 20), y + rand(-16, 16));
  }

  function onMeet(a, b, cx, cy) {
    a.classList.add('fish--flinch');
    b.classList.add('fish--flinch');
    window.setTimeout(function () {
      a.classList.remove('fish--flinch');
      b.classList.remove('fish--flinch');
    }, 900);
    if (Math.random() < 0.55) {
      a.classList.add('fish--glow');
      b.classList.add('fish--glow');
      window.setTimeout(function () {
        a.classList.remove('fish--glow');
        b.classList.remove('fish--glow');
      }, 700);
    }
    burstAt(cx, cy, Math.random() < 0.4);
  }


var JOKES = [
    'هوی بابا، بیا دیگه! چقد لفتش می‌دی؟',
    'ما اینجا بودیم. تو کجایی پس؟',
    'تمرین‌هامون گوش همسایه‌ها رو ... بیا تو هم بشنو.',
    'همسایه‌ها زنده شنیدن، تو نمی‌خوای؟',
    'به من دست زدی، حالا تا سالن هم بیا دیگه.',
    'من ماهی‌ام، نه آژانس مسافرتی. خودت بلیت بگیر بیا.',
    'هوی! اون بلیت رو می‌گیری یا باید خودم بیام دنبالت؟',
    'یه صندلی خالی واسه تو. فعلاً!',
    'گوشی رو بذار کنار، بیا یه چیزی رو زنده ببین.',
    'ساندچک رو همسایه‌ها شنیدن. تو هنوز تو فکری؟',
    'بلیت هستا. بعدا نیا بگی خبر نداشتم.',
    'هوی، من منتظرم.',
    'ما می‌ریم رو استیج. تو هم میای یا فقط حرفی؟',
    'یه شب دورهمی، چندتا آهنگ، کلی خاطره. پایه‌ای؟',
    'بیا که فرداش نگی «کاش می‌اومدم».',
    'همه میان، تو فقط داری فکر می‌کنی؟',
    'ماهی رو ول کن، بلیت رو بچسب!',
    'هوی بابا، اجرا که منتظر تصمیم تو نمی‌مونه!',
    'We Were Here. تو هم باش، دیگه.',
    'منو که انگول کردی، لاقل بیا اجرا'
];


  var jokeBag = [];
  var lastJoke = '';
  var dialog = null;
  var dialogTimer = 0;

  function nextJoke() {
    if (!jokeBag.length) {
      jokeBag = JOKES.slice();
      for (var i = jokeBag.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var t = jokeBag[i];
        jokeBag[i] = jokeBag[j];
        jokeBag[j] = t;
      }
      if (jokeBag[jokeBag.length - 1] === lastJoke) jokeBag.unshift(jokeBag.pop());
    }
    lastJoke = jokeBag.pop();
    return lastJoke;
  }

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('div');
    dialog.className = 'wwh-fish-dialog';
    dialog.setAttribute('role', 'status');
    dialog.setAttribute('aria-live', 'polite');
    dialog.innerHTML =
      '<span class="wwh-fish-dialog__who">ما اینجا بودیم</span><p class="wwh-fish-dialog__text"></p>';
    document.body.appendChild(dialog);
    dialog.addEventListener('click', hideDialog);
    return dialog;
  }

  function hideDialog() {
    if (!dialog) return;
    dialog.classList.remove('is-open');
    window.clearTimeout(dialogTimer);
  }

  function showJoke() {
    var el = ensureDialog();
    var text = el.querySelector('.wwh-fish-dialog__text');
    el.classList.remove('is-open');
    void el.offsetWidth;
    text.textContent = nextJoke();
    el.classList.add('is-open');
    window.clearTimeout(dialogTimer);
    dialogTimer = window.setTimeout(hideDialog, 5200 + text.textContent.length * 40);
  }

  function pokeFish(fish, clientX, clientY) {
    fish.classList.add('fish--flinch', 'fish--glow');
    window.setTimeout(function () {
      fish.classList.remove('fish--flinch', 'fish--glow');
    }, 900);
    burstAt(clientX, clientY, false);
    var m = fish._motion;
    if (m) {
      m.vx *= 0.6;
      m.vy -= 14;
    }
    showJoke();
  }

  function isPerfLite() {
    return document.documentElement.classList.contains('wwh-perf-lite');
  }

  function gameLoop(now) {
    if (!lastTick) lastTick = now;
    if (isPerfLite() && now - lastTick < 32) {
      loopRaf = requestAnimationFrame(gameLoop);
      return;
    }
    var dt = clamp((now - lastTick) / 1000, 0.008, 0.042);
    lastTick = now;

    fishEls.forEach(function (fish) {
      updateFish(fish, dt, now);
    });

    var active = fishEls.filter(function (f) {
      return f._swimming && f._motion;
    });
    if (active.length === 2) {
      /* No seek/meetup — keep paths independent and random */
      resolveCollision(active[0], active[1], now);
    }

    loopRaf = requestAnimationFrame(gameLoop);
  }

  function bindFish(fish) {
    fish.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      pokeFish(fish, e.clientX, e.clientY);
    });
    fish.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      var r = fish.getBoundingClientRect();
      pokeFish(fish, r.left + r.width / 2, r.top + r.height / 2);
    });
  }

  function boot() {
    if (reduceMotion) return;
    fishEls.forEach(bindFish);
    /* Start as soon as the page loads — do not wait for spotlight */
    fishEls[0]._timer = window.setTimeout(function () {
      runSwim(fishEls[0]);
    }, rand(60, 280));
    fishEls[1]._timer = window.setTimeout(function () {
      runSwim(fishEls[1]);
    }, rand(480, 1100));
    loopRaf = requestAnimationFrame(gameLoop);
  }

  loadArtwork().then(boot);

  window.addEventListener(
    'pagehide',
    function () {
      if (loopRaf) cancelAnimationFrame(loopRaf);
      fishEls.forEach(stopSwim);
    },
    { once: true }
  );
})();
