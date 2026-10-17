/**
 * WwhLightbox — full-screen media preview with swipe + prev/next.
 * API: WwhLightbox.open({ items, index, toFa?, resolveUrl? })
 * items: [{ url, kind: 'image'|'video', caption? }]
 */
(function (global) {
  'use strict';

  var FA = '۰۱۲۳۴۵۶۷۸۹';
  function defaultToFa(s) {
    return String(s).replace(/\d/g, function (d) { return FA[d]; });
  }

  function prefersReducedMotion() {
    try {
      return !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) {
      return false;
    }
  }

  function isVideoKind(item) {
    if (!item) return false;
    if (item.kind === 'video' || item.mediaKind === 'video') return true;
    var mime = item.mime || '';
    return String(mime).indexOf('video/') === 0;
  }

  var root = null;
  var stage = null;
  var slide = null;
  var counterEl = null;
  var capEl = null;
  var btnClose = null;
  var btnPrev = null;
  var btnNext = null;
  var btnPrevTop = null;
  var btnNextTop = null;

  var state = {
    open: false,
    items: [],
    index: 0,
    toFa: defaultToFa,
    resolveUrl: null,
    resolving: false,
    drag: null,
    lastFocus: null,
    closing: false
  };

  function ensureDom() {
    if (root) return;
    root = document.createElement('div');
    root.className = 'wwh-lb';
    root.id = 'wwh-lightbox';
    root.hidden = true;
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-label', 'پیش‌نمایش رسانه');
    root.innerHTML =
      '<div class="wwh-lb__top">' +
        '<button type="button" class="wwh-lb__btn wwh-lb__close" aria-label="بستن">بستن</button>' +
        '<span class="wwh-lb__counter" aria-live="polite"></span>' +
        '<div class="wwh-lb__top-nav">' +
          '<button type="button" class="wwh-lb__btn wwh-lb__prev-top" aria-label="قبلی">قبلی</button>' +
          '<button type="button" class="wwh-lb__btn wwh-lb__next-top" aria-label="بعدی">بعدی</button>' +
        '</div>' +
      '</div>' +
      '<div class="wwh-lb__stage-wrap">' +
        '<button type="button" class="wwh-lb__btn wwh-lb__nav wwh-lb__nav--prev" aria-label="قبلی">‹</button>' +
        '<div class="wwh-lb__stage" tabindex="-1">' +
          '<div class="wwh-lb__slide"></div>' +
        '</div>' +
        '<button type="button" class="wwh-lb__btn wwh-lb__nav wwh-lb__nav--next" aria-label="بعدی">›</button>' +
      '</div>' +
      '<div class="wwh-lb__bottom"><p class="wwh-lb__cap"></p></div>';

    document.body.appendChild(root);

    stage = root.querySelector('.wwh-lb__stage');
    slide = root.querySelector('.wwh-lb__slide');
    counterEl = root.querySelector('.wwh-lb__counter');
    capEl = root.querySelector('.wwh-lb__cap');
    btnClose = root.querySelector('.wwh-lb__close');
    btnPrev = root.querySelector('.wwh-lb__nav--prev');
    btnNext = root.querySelector('.wwh-lb__nav--next');
    btnPrevTop = root.querySelector('.wwh-lb__prev-top');
    btnNextTop = root.querySelector('.wwh-lb__next-top');

    btnClose.addEventListener('click', close);
    btnPrev.addEventListener('click', function () { go(-1); });
    btnNext.addEventListener('click', function () { go(1); });
    btnPrevTop.addEventListener('click', function () { go(-1); });
    btnNextTop.addEventListener('click', function () { go(1); });

    root.addEventListener('click', function (e) {
      if (e.target === root || e.target.classList.contains('wwh-lb__stage-wrap')) {
        close();
      }
    });

    bindPointer(stage);
    document.addEventListener('keydown', onKeydown);
  }

  function onKeydown(e) {
    if (!state.open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      // physical left → next in RTL reading order
      go(document.documentElement.dir === 'rtl' ? 1 : -1);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      go(document.documentElement.dir === 'rtl' ? -1 : 1);
    }
  }

  function bindPointer(el) {
    var startX = 0;
    var startY = 0;
    var startT = 0;
    var dx = 0;
    var dy = 0;
    var axis = null;
    var active = false;
    var pid = null;

    function onDown(e) {
      if (!state.open || state.resolving) return;
      if (e.button != null && e.button !== 0) return;
      if (e.target && e.target.closest && e.target.closest('video, button, a')) return;
      active = true;
      pid = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      startT = Date.now();
      dx = 0;
      dy = 0;
      axis = null;
      try { el.setPointerCapture(pid); } catch (err) {}
      el.classList.add('is-dragging');
      slide.style.transition = 'none';
    }

    function onMove(e) {
      if (!active || e.pointerId !== pid) return;
      dx = e.clientX - startX;
      dy = e.clientY - startY;
      if (!axis) {
        if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
        axis = Math.abs(dx) >= Math.abs(dy) ? 'x' : 'y';
        if (axis === 'y') {
          active = false;
          el.classList.remove('is-dragging');
          slide.style.transition = '';
          slide.style.transform = '';
          slide.style.opacity = '';
          try { el.releasePointerCapture(pid); } catch (err) {}
          return;
        }
      }
      if (axis !== 'x') return;
      e.preventDefault();
      var w = el.clientWidth || 1;
      var opacity = 1 - Math.min(0.35, Math.abs(dx) / w * 0.5);
      if (prefersReducedMotion()) {
        slide.style.opacity = String(opacity);
      } else {
        slide.style.transform = 'translateX(' + dx + 'px)';
        slide.style.opacity = String(opacity);
      }
    }

    function onUp(e) {
      if (!active || e.pointerId !== pid) return;
      active = false;
      el.classList.remove('is-dragging');
      try { el.releasePointerCapture(pid); } catch (err) {}

      var w = el.clientWidth || 1;
      var dt = Math.max(1, Date.now() - startT);
      var velocity = Math.abs(dx) / dt;
      var commit = axis === 'x' && (Math.abs(dx) >= w * 0.2 || velocity > 0.45);

      slide.style.transition = '';
      if (commit) {
        var dir = dx < 0 ? 1 : -1;
        // In RTL, finger swipe left still advances to next (same as LTR Instagram-like)
        go(dir, dx);
      } else {
        slide.style.transform = '';
        slide.style.opacity = '';
      }
      axis = null;
      dx = 0;
      dy = 0;
    }

    el.addEventListener('pointerdown', onDown);
    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerup', onUp);
    el.addEventListener('pointercancel', onUp);
  }

  function updateChrome() {
    var n = state.items.length;
    var i = state.index;
    var label = state.toFa(i + 1) + ' / ' + state.toFa(n);
    if (counterEl) counterEl.textContent = n ? label : '';
    var item = state.items[i];
    if (capEl) capEl.textContent = (item && (item.caption || item.title)) || '';

    var atStart = i <= 0;
    var atEnd = i >= n - 1;
    [btnPrev, btnPrevTop].forEach(function (b) {
      if (b) b.disabled = atStart || n < 2;
    });
    [btnNext, btnNextTop].forEach(function (b) {
      if (b) b.disabled = atEnd || n < 2;
    });
  }

  function clearSlide() {
    if (!slide) return;
    var v = slide.querySelector('video');
    if (v) {
      try { v.pause(); } catch (e) {}
    }
    slide.innerHTML = '';
    slide.style.transform = '';
    slide.style.opacity = '';
  }

  function renderItem(fromDx) {
    var item = state.items[state.index];
    if (!item) {
      clearSlide();
      updateChrome();
      return;
    }
    updateChrome();
    state.resolving = true;

    var enterFrom = 0;
    if (typeof fromDx === 'number' && fromDx !== 0) {
      enterFrom = fromDx < 0 ? 40 : -40;
    }

    function paint(url) {
      clearSlide();
      var reduced = prefersReducedMotion();
      if (!reduced && enterFrom) {
        slide.style.transition = 'none';
        slide.style.transform = 'translateX(' + enterFrom + 'px) scale(0.98)';
        slide.style.opacity = '0.55';
      } else if (!reduced) {
        slide.style.transition = 'none';
        slide.style.transform = 'scale(0.97)';
        slide.style.opacity = '0.7';
      }

      if (isVideoKind(item)) {
        var v = document.createElement('video');
        v.src = url;
        v.controls = true;
        v.playsInline = true;
        v.setAttribute('playsinline', '');
        v.preload = 'metadata';
        slide.appendChild(v);
      } else {
        var img = document.createElement('img');
        img.src = url;
        img.alt = item.caption || item.title || '';
        img.draggable = false;
        slide.appendChild(img);
      }

      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          slide.style.transition = '';
          slide.style.transform = '';
          slide.style.opacity = '';
          state.resolving = false;
        });
      });
    }

    var resolver = state.resolveUrl;
    if (typeof resolver === 'function') {
      Promise.resolve(resolver(item, state.index)).then(function (url) {
        if (!state.open) return;
        paint(url || item.url);
      }).catch(function () {
        if (!state.open) return;
        clearSlide();
        slide.textContent = 'پیش‌نمایش در دسترس نیست';
        state.resolving = false;
      });
    } else {
      paint(item.url);
    }
  }

  function go(delta, fromDx) {
    if (!state.open || state.resolving) return;
    var next = state.index + delta;
    if (next < 0 || next >= state.items.length) {
      if (slide) {
        slide.style.transform = '';
        slide.style.opacity = '';
      }
      return;
    }
    state.index = next;
    renderItem(typeof fromDx === 'number' ? fromDx : (delta > 0 ? -1 : 1));
  }

  function lockScroll(lock) {
    if (lock) {
      state._scrollY = global.scrollY || 0;
      document.documentElement.style.overflow = 'hidden';
      document.body.style.overflow = 'hidden';
    } else {
      document.documentElement.style.overflow = '';
      document.body.style.overflow = '';
    }
  }

  function open(opts) {
    opts = opts || {};
    var items = opts.items || [];
    if (!items.length) return;

    ensureDom();
    state.items = items.slice();
    state.index = Math.max(0, Math.min(opts.index | 0, items.length - 1));
    state.toFa = typeof opts.toFa === 'function' ? opts.toFa : defaultToFa;
    state.resolveUrl = typeof opts.resolveUrl === 'function' ? opts.resolveUrl : null;
    state.closing = false;
    state.lastFocus = document.activeElement;

    root.hidden = false;
    root.classList.remove('is-closing');
    lockScroll(true);
    state.open = true;

    renderItem(0);

    requestAnimationFrame(function () {
      root.classList.add('is-open');
      if (btnClose) btnClose.focus();
    });
  }

  function close() {
    if (!state.open || state.closing) return;
    state.closing = true;
    clearSlide();
    root.classList.remove('is-open');
    root.classList.add('is-closing');

    var done = function () {
      root.hidden = true;
      root.classList.remove('is-closing');
      state.open = false;
      state.closing = false;
      state.items = [];
      lockScroll(false);
      if (state.lastFocus && state.lastFocus.focus) {
        try { state.lastFocus.focus(); } catch (e) {}
      }
    };

    if (prefersReducedMotion()) {
      done();
    } else {
      setTimeout(done, 220);
    }
  }

  function isOpen() {
    return !!state.open;
  }

  global.WwhLightbox = {
    open: open,
    close: close,
    isOpen: isOpen,
    go: go
  };
})(typeof window !== 'undefined' ? window : this);
