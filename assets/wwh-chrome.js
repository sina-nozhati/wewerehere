/**
 * Shared topbar + footer for public pages (not admin).
 */
(function () {
  'use strict';

  if (document.body && document.body.getAttribute('data-wwh-chrome') === 'off') return;

  var MIC_SVG =
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="square" aria-hidden="true">' +
    '<rect x="9" y="2" width="6" height="11" />' +
    '<path d="M5 10v1a7 7 0 0 0 14 0v-1" />' +
    '<line x1="12" y1="18" x2="12" y2="22" />' +
    '<line x1="8" y1="22" x2="16" y2="22" />' +
    '</svg>';

  var FOOTER_MARK_SVG =
    '<svg class="wwh-footer__mark footer__mark" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="square" aria-hidden="true">' +
    '<rect x="9" y="2" width="6" height="11" />' +
    '<path d="M5 10v1a7 7 0 0 0 14 0v-1" />' +
    '<line x1="12" y1="18" x2="12" y2="22" />' +
    '<line x1="8" y1="22" x2="16" y2="22" />' +
    '</svg>';

  var TOP_LINKS = [
    { href: '/episodes', label: 'اپیزودها', match: /^\/episodes\/?$/ },
    { href: '/#register', label: 'رزرو حضور', match: null },
    { href: '/track', label: 'پیگیری رزرو', match: /^\/track\/?$/ },
    { href: '/support', label: 'پشتیبانی', match: /^\/support\/?$/ },
  ];

  var FOOTER_LINKS = [
    { href: '/episodes', label: 'اپیزودها', match: /^\/episodes\/?$/ },
    { href: '/#register', label: 'رزرو حضور', match: null },
    { href: '/#setlist', label: 'ست لیست', match: null },
    { href: '/track', label: 'پیگیری رزرو', match: /^\/track\/?$/ },
    { href: '/support', label: 'پشتیبانی', match: /^\/support\/?$/ },
    { href: '/#access', label: 'دسترسی بعد از اجرا', match: null },
  ];

  function pathname() {
    var p = window.location.pathname || '/';
    if (p.length > 1 && p.endsWith('/')) p = p.slice(0, -1);
    if (p === '/index.html') return '/';
    return p;
  }

  function isCurrent(link) {
    if (!link.match) return false;
    return link.match.test(pathname());
  }

  function navLinksHtml(links, className) {
    return links
      .map(function (link) {
        var cur = isCurrent(link) ? ' aria-current="page"' : '';
        var cls = className ? ' class="' + className + '"' : '';
        return '<a' + cls + ' href="' + link.href + '"' + cur + '>' + link.label + '</a>';
      })
      .join('');
  }

  function topbarHtml() {
    return (
      '<header class="wwh-topbar" role="banner">' +
      '<a class="wwh-topbar__brand" href="/">' +
      MIC_SVG +
      '<span>ما اینجا بودیم</span></a>' +
      '<button type="button" class="wwh-topbar__menu-btn" id="wwh-topbar-menu-btn" aria-expanded="false" aria-controls="wwh-topbar-menu" aria-label="باز کردن منو">' +
      '<span class="wwh-topbar__menu-icon" aria-hidden="true">' +
      '<span></span><span></span><span></span></span></button>' +
      '<nav class="wwh-topbar__nav" id="wwh-topbar-menu" aria-label="ناوبری اصلی">' +
      navLinksHtml(TOP_LINKS, 'wwh-topbar__link') +
      '</nav></header>'
    );
  }

  function setMenuOpen(bar, open) {
    if (!bar) return;
    var btn = bar.querySelector('.wwh-topbar__menu-btn');
    bar.classList.toggle('is-menu-open', open);
    document.body.classList.toggle('wwh-nav-open', open);
    if (btn) {
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.setAttribute('aria-label', open ? 'بستن منو' : 'باز کردن منو');
    }
    if (open) measureTopbar();
  }

  function bindMobileNav() {
    var bar = document.querySelector('.wwh-topbar');
    if (!bar || bar.dataset.wwhNavBound === '1') return;
    bar.dataset.wwhNavBound = '1';
    var btn = bar.querySelector('.wwh-topbar__menu-btn');
    var nav = bar.querySelector('.wwh-topbar__nav');
    if (!btn || !nav) return;

    btn.addEventListener('click', function () {
      setMenuOpen(bar, !bar.classList.contains('is-menu-open'));
    });

    nav.addEventListener('click', function (e) {
      if (e.target.closest('.wwh-topbar__link') || e.target === nav) setMenuOpen(bar, false);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && bar.classList.contains('is-menu-open')) {
        setMenuOpen(bar, false);
        btn.focus();
      }
    });

    window.addEventListener(
      'resize',
      function () {
        if (window.matchMedia('(min-width: 768px)').matches) setMenuOpen(bar, false);
      },
      { passive: true }
    );
  }

  function footerHtml() {
    return (
      '<footer class="wwh-footer footer" role="contentinfo">' +
      '<div class="wwh-footer__inner container">' +
      FOOTER_MARK_SVG +
      '<p class="wwh-footer__brand footer__brand">ما اینجا بودیم</p>' +
      '<p class="wwh-footer__text footer__text" id="footer-meta">ما اینجا بودیم</p>' +
      '<nav class="wwh-footer__nav footer__nav" aria-label="دسترسی سریع">' +
      navLinksHtml(FOOTER_LINKS, '') +
      '</nav></div></footer>'
    );
  }

  function ensureMount(id, position) {
    var el = document.getElementById(id);
    if (el) return el;
    el = document.createElement('div');
    el.id = id;
    if (position === 'first') {
      document.body.insertBefore(el, document.body.firstChild);
    } else {
      document.body.appendChild(el);
    }
    return el;
  }

  function measureTopbar() {
    var bar = document.querySelector('.wwh-topbar');
    if (!bar) return;
    var h = Math.round(bar.getBoundingClientRect().height);
    if (h > 0) document.documentElement.style.setProperty('--wwh-topbar-height', h + 'px');
  }

  function loadFooterMeta() {
    var path = pathname();
    if (path === '/') return;
    var el = document.getElementById('footer-meta');
    if (!el) return;
    fetch('/api/landing')
      .then(function (r) {
        return r.ok ? r.json() : Promise.reject();
      })
      .then(function (data) {
        var ev = data && data.event;
        if (!ev) return;
        var cap = data.capacity;
        if (window.WwhDateTime && window.WwhDateTime.formatFooterMeta) {
          el.textContent = window.WwhDateTime.formatFooterMeta(ev, cap);
        } else if (ev.title) {
          el.textContent = ev.title;
        }
      })
      .catch(function () {
        /* keep fallback */
      });
  }

  function applyBodyClass() {
    var path = pathname();
    document.body.classList.add('wwh-has-chrome');
    if (path === '/track') document.body.classList.add('wwh-page-track');
    if (path === '/support') document.body.classList.add('wwh-page-support');
    if (path === '/episodes') document.body.classList.add('wwh-page-episodes');
  }

  function init() {
    if (document.body.getAttribute('data-wwh-chrome') === 'off') return;

    var topMount = ensureMount('wwh-topbar-mount', 'first');
    if (!topMount.querySelector('.wwh-topbar')) {
      topMount.innerHTML = topbarHtml();
    }

    var footMount = ensureMount('wwh-footer-mount', 'last');
    footMount.innerHTML = footerHtml();

    applyBodyClass();
    bindMobileNav();
    measureTopbar();
    window.addEventListener('resize', measureTopbar, { passive: true });
    loadFooterMeta();
  }

  if (document.body) {
    init();
  } else {
    document.addEventListener('DOMContentLoaded', init);
  }
})();
