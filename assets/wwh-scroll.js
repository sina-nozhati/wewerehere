(function () {
  var bar = document.getElementById('scroll-progress');
  if (!bar) return;

  var ticking = false;

  function update() {
    ticking = false;
    var doc = document.documentElement;
    var scrollTop = window.scrollY || doc.scrollTop;
    var height = doc.scrollHeight - window.innerHeight;
    var p = height > 0 ? Math.min(1, Math.max(0, scrollTop / height)) : 0;
    bar.style.transform = 'scaleX(' + p + ')';
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(update);
    }
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  update();
})();
