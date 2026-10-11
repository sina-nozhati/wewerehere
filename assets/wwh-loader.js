/**
 * Gothic loader — until load + landing API + fonts; arms spotlight under overlay, then fades.
 */
(function () {
  var MIN_VISIBLE_MS = 2000;
  /** Match spotlight travel (~820ms) so first target is locked before loader fades. */
  var SPOTLIGHT_SYNC_MS = 900;

  function wait(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function whenReady() {
    var loadP = new Promise(function (resolve) {
      if (document.readyState === 'complete') resolve();
      else window.addEventListener('load', resolve, { once: true });
    });
    var apiP = new Promise(function (resolve) {
      if (window.__wwhEventAt) resolve();
      else window.addEventListener('wwh:event-ready', resolve, { once: true });
    });
    var fontsP =
      document.fonts && document.fonts.ready ? document.fonts.ready.catch(function () {}) : Promise.resolve();
    return Promise.all([loadP, apiP, fontsP]);
  }

  function dispatch(name) {
    try {
      window.dispatchEvent(new CustomEvent(name));
    } catch (e) {
      /* IE */
    }
  }

  function init() {
    var loader = document.getElementById('wwh-loader');
    if (!loader) {
      document.documentElement.classList.remove('wwh-loading');
      window.__wwhLoaderDone = true;
      dispatch('wwh:loader-done');
      return;
    }

    document.documentElement.classList.add('wwh-loading');
    var t0 = performance.now();

    whenReady()
      .then(function () {
        var elapsed = performance.now() - t0;
        if (elapsed < MIN_VISIBLE_MS) return wait(MIN_VISIBLE_MS - elapsed);
      })
      .then(function () {
        dispatch('wwh:loader-arm-spotlight');
        document.documentElement.classList.remove('wwh-loading');
        return wait(SPOTLIGHT_SYNC_MS);
      })
      .then(function () {
        loader.classList.add('is-exit');
        return new Promise(function (resolve) {
          var settled = false;
          var fallback = setTimeout(finish, 750);

          function finish(event) {
            if (settled || (event && event.propertyName !== 'opacity')) return;
            settled = true;
            clearTimeout(fallback);
            loader.removeEventListener('transitionend', finish);
            resolve();
          }

          loader.addEventListener('transitionend', finish);
        });
      })
      .then(finishLoader)
      .catch(function () {
        finishLoader();
      });

    function finishLoader() {
      if (window.__wwhLoaderDone) return;
      loader.classList.add('is-done');
      document.documentElement.classList.remove('wwh-loading');
      window.__wwhLoaderDone = true;
      dispatch('wwh:loader-done');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
