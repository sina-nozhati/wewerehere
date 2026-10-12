/**
 * Gothic loader — until load + landing API + fonts; arms spotlight under overlay, then fades.
 */
(function () {
  function isLite() {
    var root = document.documentElement;
    return (
      root.classList.contains('wwh-perf-lite') ||
      root.classList.contains('wwh-touch') ||
      root.classList.contains('wwh-loader-simple')
    );
  }

  var MIN_VISIBLE_MS = isLite() ? 1050 : 2000;
  /** Let spotlight reach title before loader fully lifts */
  var SPOTLIGHT_SYNC_MS = isLite() ? 720 : 1050;
  var FONT_WAIT_MS = isLite() ? 750 : 5000;

  function wait(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function whenFonts() {
    if (!document.fonts) return Promise.resolve();
    if (isLite()) {
      var loads = [];
      try {
        loads.push(document.fonts.load('900 1.05rem Vazirmatn'));
        loads.push(document.fonts.load('700 1rem Vazirmatn'));
      } catch (e) {
        return wait(FONT_WAIT_MS);
      }
      return Promise.race([Promise.all(loads), wait(FONT_WAIT_MS)]).catch(function () {});
    }
    return Promise.race([document.fonts.ready, wait(FONT_WAIT_MS)]).catch(function () {});
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
    return Promise.all([loadP, apiP, whenFonts()]);
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
        var minVis = isLite() ? 1050 : 2000;
        if (elapsed < minVis) return wait(minVis - elapsed);
      })
      .then(function () {
        dispatch('wwh:loader-arm-spotlight');
        document.documentElement.classList.remove('wwh-loading');
        var sync = isLite() ? 480 : 900;
        return wait(sync);
      })
      .then(function () {
        loader.classList.add('is-exit');
        return new Promise(function (resolve) {
          var settled = false;
          var fallback = setTimeout(finish, isLite() ? 520 : 750);

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
