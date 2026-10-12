/**
 * Hero visibility + ember budget — pause heavy ambience when hero is off-screen or spotlight runs.
 */
(function () {
  'use strict';

  var hero = document.getElementById('hero');
  var embersWrap = document.getElementById('embers');
  var root = document.documentElement;
  var coarse = window.matchMedia('(hover: none) and (pointer: coarse)').matches;
  var lite =
    root.classList.contains('wwh-perf-lite') || root.classList.contains('wwh-touch') || coarse;

  if (coarse) root.classList.add('wwh-touch');
  root.classList.add('wwh-hero-inview');

  var heroInView = true;
  var emberTimer = 0;
  var maxEmbers = lite ? 8 : 14;
  var emberInterval = lite ? 2800 : 1600;

  function setHeroInView(on) {
    heroInView = on;
    root.classList.toggle('wwh-hero-inview', on);
  }

  if (hero && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(
      function (entries) {
        var e = entries[0];
        setHeroInView(e.isIntersecting && e.intersectionRatio > 0.08);
      },
      { threshold: [0, 0.08, 0.2, 0.5] }
    );
    io.observe(hero);
  } else {
    setHeroInView(true);
  }

  window.__wwhHeroInView = function () {
    return heroInView && !root.classList.contains('wwh-spotlight-active');
  };

  function spawnEmber() {
    if (!embersWrap || !heroInView) return;
    if (root.classList.contains('wwh-spotlight-active')) return;
    if (embersWrap.children.length >= maxEmbers) return;

    var e = document.createElement('span');
    e.className = 'ember';
    e.style.left = (2 + Math.random() * 96) + 'vw';
    e.style.setProperty('--drift', ((Math.random() - 0.5) * 160).toFixed(0) + 'px');
    e.style.animationDuration = (7 + Math.random() * 9).toFixed(1) + 's';
    e.style.animationDelay = (Math.random() * 5).toFixed(1) + 's';
    embersWrap.appendChild(e);
    e.addEventListener(
      'animationend',
      function () {
        e.remove();
      },
      { once: true }
    );
  }

  function startEmbers() {
    if (!embersWrap) return;
    var initial = lite ? 6 : 10;
    for (var i = 0; i < initial; i++) {
      window.setTimeout(spawnEmber, i * (lite ? 700 : 500));
    }
    emberTimer = window.setInterval(function () {
      if (heroInView && !root.classList.contains('wwh-spotlight-active')) spawnEmber();
    }, emberInterval);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startEmbers);
  } else {
    startEmbers();
  }

  window.addEventListener(
    'pagehide',
    function () {
      if (emberTimer) window.clearInterval(emberTimer);
    },
    { once: true }
  );
})();
