/**
 * Shared MapLibre + OpenFreeMap helpers and native directions (geo: / OS chooser).
 * Requires maplibre-gl to be loaded before createMap / setMarker.
 */
(function (global) {
  'use strict';

  // Fiord = navy / carbon-blue (better contrast than Dark Matter for our UI)
  var STYLE_URL = 'https://tiles.openfreemap.org/styles/fiord';
  var ML_CSS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css';
  var ML_JS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js';
  // Arabic shaping + BiDi — without this, Persian letters render disconnected
  var RTL_PLUGIN =
    'https://unpkg.com/@mapbox/mapbox-gl-rtl-text@0.2.3/mapbox-gl-rtl-text.min.js';
  var DEFAULT_CENTER = [51.389, 35.6892]; // Tehran [lng, lat]
  var DEFAULT_ZOOM = 12;
  var VENUE_ZOOM = 16; // street-level, matches Neshan place links

  var loadPromise = null;
  var rtlPromise = null;

  function loadMapLibre() {
    if (global.maplibregl) return Promise.resolve(global.maplibregl);
    if (loadPromise) return loadPromise;
    loadPromise = new Promise(function (resolve, reject) {
      if (!document.querySelector('link[data-wwh-maplibre]')) {
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = ML_CSS;
        link.setAttribute('data-wwh-maplibre', '1');
        document.head.appendChild(link);
      }
      var existing = document.querySelector('script[data-wwh-maplibre]');
      if (existing) {
        existing.addEventListener('load', function () {
          resolve(global.maplibregl);
        });
        existing.addEventListener('error', reject);
        return;
      }
      var s = document.createElement('script');
      s.src = ML_JS;
      s.async = true;
      s.setAttribute('data-wwh-maplibre', '1');
      s.onload = function () {
        resolve(global.maplibregl);
      };
      s.onerror = reject;
      document.head.appendChild(s);
    });
    return loadPromise;
  }

  function ensureRtlPlugin(ml) {
    if (rtlPromise) return rtlPromise;
    rtlPromise = new Promise(function (resolve) {
      try {
        // lazy=false so Persian labels shape before first paint
        var result = ml.setRTLTextPlugin(RTL_PLUGIN, false);
        if (result && typeof result.then === 'function') {
          result.then(function () { resolve(); }).catch(function () { resolve(); });
        } else {
          resolve();
        }
      } catch (err) {
        resolve();
      }
    });
    return rtlPromise;
  }

  /**
   * Fiord → deeper carbon navy, and hide tile labels.
   * OpenFreeMap glyph PBFs don't shape Persian well (letters stay disconnected
   * even with the RTL plugin); venue name stays in our UI with Vazirmatn.
   */
  function polishMapStyle(map) {
    var style = map.getStyle();
    if (!style || !style.layers) return;
    style.layers.forEach(function (layer) {
      var id = layer.id || '';
      try {
        if (layer.type === 'symbol') {
          map.setLayoutProperty(id, 'visibility', 'none');
          return;
        }
        if (layer.type === 'background') {
          map.setPaintProperty(id, 'background-color', '#0a1628');
        } else if (layer.type === 'fill' && /water|ocean|river|lake|sea/i.test(id)) {
          map.setPaintProperty(id, 'fill-color', '#163a5f');
        } else if (layer.type === 'line' && /water/i.test(id)) {
          map.setPaintProperty(id, 'line-color', '#1e4a73');
        } else if (layer.type === 'fill' && /landcover|landuse|park|wood|grass/i.test(id)) {
          var cur = map.getPaintProperty(id, 'fill-color');
          if (typeof cur === 'string') {
            map.setPaintProperty(id, 'fill-color', '#122033');
          }
        }
      } catch (err) {
        /* layer may use data-driven paint — skip */
      }
    });
  }

  function createMap(container, opts) {
    opts = opts || {};
    var lng = opts.lng != null ? Number(opts.lng) : DEFAULT_CENTER[0];
    var lat = opts.lat != null ? Number(opts.lat) : DEFAULT_CENTER[1];
    var zoom = opts.zoom != null ? opts.zoom : DEFAULT_ZOOM;
    return loadMapLibre()
      .then(function (ml) {
        return ensureRtlPlugin(ml).then(function () {
          return ml;
        });
      })
      .then(function (ml) {
        var map = new ml.Map({
          container: container,
          style: STYLE_URL,
          center: [lng, lat],
          zoom: zoom,
          attributionControl: true,
          cooperativeGestures: !!opts.cooperativeGestures,
        });
        map.addControl(new ml.NavigationControl({ showCompass: false }), 'top-left');
        map.once('load', function () {
          polishMapStyle(map);
        });
        return map;
      });
  }

  function makeMarkerEl(label) {
    var wrap = document.createElement('div');
    wrap.className = 'wwh-map-place';
    var pin = document.createElement('div');
    pin.className = 'wwh-map-marker';
    pin.setAttribute('aria-hidden', 'true');
    wrap.appendChild(pin);
    var text = label != null ? String(label).trim() : '';
    if (text) {
      var lab = document.createElement('div');
      lab.className = 'wwh-map-place__label';
      lab.textContent = text;
      wrap.appendChild(lab);
    }
    return wrap;
  }

  /**
   * Place pin + optional Persian HTML label (Vazirmatn — not tile glyphs).
   * @param {object} markerRef `{ current }`
   * @param {string} [label]
   * @param {{ zoom?: number }} [opts]
   */
  function setMarker(map, lng, lat, markerRef, label, opts) {
    opts = opts || {};
    return loadMapLibre().then(function (ml) {
      var text = label != null ? String(label).trim() : '';
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
      markerRef.current = new ml.Marker({
        element: makeMarkerEl(text),
        anchor: text ? 'bottom' : 'bottom',
        offset: text ? [0, 0] : [0, 0],
      })
        .setLngLat([lng, lat])
        .addTo(map);
      var reduced =
        global.matchMedia &&
        global.matchMedia('(prefers-reduced-motion: reduce)').matches;
      var center = [lng, lat];
      var zoom =
        opts.zoom != null
          ? Number(opts.zoom)
          : Math.max(map.getZoom(), VENUE_ZOOM);
      if (reduced) {
        map.jumpTo({ center: center, zoom: zoom });
      } else {
        map.flyTo({ center: center, zoom: zoom, essential: true });
      }
      return markerRef.current;
    });
  }

  /**
   * Extract lat/lng from Neshan / Google share URLs.
   * Neshan: ...#c37.492-49.405-16z-0p
   * Google: .../@37.492,49.405,16z or ?q=37.492,49.405
   */
  function parseMapsUrl(raw) {
    var s = String(raw || '').trim();
    if (!s) return null;
    var m = s.match(/#c(-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)/i);
    if (m) {
      return { lat: Number(m[1]), lng: Number(m[2]) };
    }
    m = s.match(/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/);
    if (m) {
      return { lat: Number(m[1]), lng: Number(m[2]) };
    }
    m = s.match(/[?&#](?:q|query|destination)=(-?\d+(?:\.\d+)?)%2C(-?\d+(?:\.\d+)?)/i);
    if (m) {
      return { lat: Number(m[1]), lng: Number(m[2]) };
    }
    m = s.match(/[?&#](?:q|query|destination)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/i);
    if (m) {
      return { lat: Number(m[1]), lng: Number(m[2]) };
    }
    return null;
  }

  function isIosDevice() {
    var ua = navigator.userAgent || '';
    return (
      /iPad|iPhone|iPod/.test(ua) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
    );
  }

  function isAndroidDevice() {
    return /Android/i.test(navigator.userAgent || '');
  }

  /** Fixed lat,lng string for map URLs (no locale comma). */
  function coordPair(lat, lng) {
    return Number(lat).toFixed(6) + ',' + Number(lng).toFixed(6);
  }

  /**
   * Official Google Maps URLs:
   * https://developers.google.com/maps/documentation/urls/get-started
   * - Directions: /maps/dir/?api=1&destination=LAT,LNG&travelmode=driving
   * - Search/pin:  /maps/search/?api=1&query=LAT,LNG
   * Comma in lat,lng must be encoded as %2C once (encodeURIComponent).
   */
  function googleDirectionsUrl(lat, lng) {
    var dest = coordPair(lat, lng);
    return (
      'https://www.google.com/maps/dir/?api=1&destination=' +
      encodeURIComponent(dest) +
      '&travelmode=driving'
    );
  }

  function googlePinUrl(lat, lng) {
    var dest = coordPair(lat, lng);
    return (
      'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(dest)
    );
  }

  /** Neshan — reliable web fallback in Iran (Google Maps web often blank/black). */
  function neshanUrl(lat, lng) {
    return (
      'https://nshn.ir/?lat=' +
      encodeURIComponent(String(Number(lat))) +
      '&lng=' +
      encodeURIComponent(String(Number(lng)))
    );
  }

  function baladUrl(lat, lng) {
    return (
      'https://balad.ir/directions?destination.latitude=' +
      encodeURIComponent(String(Number(lat))) +
      '&destination.longitude=' +
      encodeURIComponent(String(Number(lng)))
    );
  }

  function appleMapsUrl(lat, lng) {
    return (
      'https://maps.apple.com/?daddr=' +
      encodeURIComponent(coordPair(lat, lng)) +
      '&dirflg=d'
    );
  }

  function geoUri(lat, lng, label) {
    var dest = coordPair(lat, lng);
    var labelText = label != null ? String(label).trim().slice(0, 80) : '';
    return (
      'geo:' +
      dest +
      '?q=' +
      dest +
      (labelText ? '(' + encodeURIComponent(labelText) + ')' : '')
    );
  }

  function openExternal(url) {
    global.open(url, '_blank', 'noopener,noreferrer');
  }

  function ensureChooserStyles() {
    if (document.getElementById('wwh-map-chooser-css')) return;
    var style = document.createElement('style');
    style.id = 'wwh-map-chooser-css';
    style.textContent =
      '.wwh-map-chooser{position:fixed;inset:0;z-index:10050;display:flex;align-items:flex-end;justify-content:center;' +
      'padding:max(12px,env(safe-area-inset-bottom)) 12px 12px;background:rgba(6,8,14,.55);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);' +
      'font-family:inherit;direction:rtl}' +
      '.wwh-map-chooser__sheet{width:min(420px,100%);background:#141820;color:#e8eef6;border:1px solid rgba(196,184,214,.28);' +
      'border-radius:16px;padding:18px 16px 14px;box-shadow:0 18px 48px rgba(0,0,0,.45)}' +
      '.wwh-map-chooser__title{margin:0 0 6px;font-size:1.05rem;font-weight:700;text-align:center}' +
      '.wwh-map-chooser__hint{margin:0 0 14px;font-size:.86rem;line-height:1.55;opacity:.78;text-align:center}' +
      '.wwh-map-chooser__btn{display:block;width:100%;margin:0 0 8px;padding:13px 14px;border-radius:12px;border:1px solid rgba(196,184,214,.35);' +
      'background:transparent;color:inherit;font:inherit;font-size:.95rem;font-weight:600;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent}' +
      '.wwh-map-chooser__btn--primary{background:rgba(212,63,90,.16);border-color:rgba(212,63,90,.55)}' +
      '.wwh-map-chooser__btn:active{transform:scale(.98)}' +
      '.wwh-map-chooser__cancel{margin-top:4px;border-color:transparent;opacity:.7;font-weight:500}';
    document.head.appendChild(style);
  }

  function closeMapChooser(root) {
    if (!root || !root.parentNode) return;
    try {
      root.parentNode.removeChild(root);
    } catch (e) { /* ignore */ }
    document.documentElement.classList.remove('wwh-map-chooser-open');
  }

  /**
   * iPhone/iPad: let the guest pick Apple Maps or Google Maps.
   * https://maps.apple.com opens Apple Maps; Google’s /maps/dir URL opens the
   * Google Maps app when installed, otherwise Safari.
   */
  function showIosMapChooser(lat, lng) {
    ensureChooserStyles();
    closeMapChooser(document.getElementById('wwh-map-chooser'));

    var root = document.createElement('div');
    root.id = 'wwh-map-chooser';
    root.className = 'wwh-map-chooser';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-label', 'انتخاب نقشه');
    root.innerHTML =
      '<div class="wwh-map-chooser__sheet">' +
        '<p class="wwh-map-chooser__title">مسیریابی با کدام نقشه؟</p>' +
        '<p class="wwh-map-chooser__hint">روی آیفون می‌تونی نقشه‌های اپل یا گوگل مپ را انتخاب کنی.</p>' +
        '<button type="button" class="wwh-map-chooser__btn wwh-map-chooser__btn--primary" data-map="apple">نقشه‌های اپل</button>' +
        '<button type="button" class="wwh-map-chooser__btn" data-map="google">گوگل مپ</button>' +
        '<button type="button" class="wwh-map-chooser__btn wwh-map-chooser__cancel" data-map="cancel">انصراف</button>' +
      '</div>';

    function onPick(e) {
      var btn = e.target.closest('[data-map]');
      if (!btn) return;
      var which = btn.getAttribute('data-map');
      closeMapChooser(root);
      if (which === 'apple') {
        global.location.href = appleMapsUrl(lat, lng);
      } else if (which === 'google') {
        // Universal / web URL — iOS opens Google Maps app if present
        global.location.href = googleDirectionsUrl(lat, lng);
      }
    }

    root.addEventListener('click', function (e) {
      if (e.target === root) {
        closeMapChooser(root);
        return;
      }
      onPick(e);
    });

    document.documentElement.classList.add('wwh-map-chooser-open');
    document.body.appendChild(root);
  }

  /**
   * Open directions:
   * 1) Android → geo: (OS “Open with…” → Google / Neshan / Balad apps)
   * 2) iOS → sheet: Apple Maps or Google Maps
   * 3) Web fallback → Neshan (works in IR); Google Maps web is last resort
   *    because /maps/dir often renders a black/blank page on IR networks.
   */
  function openDirections(lat, lng, label) {
    var la = Number(lat);
    var ln = Number(lng);
    if (!Number.isFinite(la) || !Number.isFinite(ln)) return;

    var webFallback = neshanUrl(la, ln);

    if (isIosDevice()) {
      showIosMapChooser(la, ln);
      return;
    }

    if (isAndroidDevice()) {
      var leftPage = false;
      function markLeft() {
        leftPage = true;
      }
      document.addEventListener('visibilitychange', markLeft);
      global.addEventListener('pagehide', markLeft);
      global.location.href = geoUri(la, ln, label);
      global.setTimeout(function () {
        document.removeEventListener('visibilitychange', markLeft);
        global.removeEventListener('pagehide', markLeft);
        if (!leftPage && !document.hidden) {
          // geo: ignored by browser → Neshan web (not Google — often black in IR)
          global.location.href = webFallback;
        }
      }, 1400);
      return;
    }

    // Desktop / other: Neshan web (reliable in IR). Google Maps web often blacks out.
    openExternal(webFallback);
  }

  function parseCoord(raw) {
    if (raw == null || String(raw).trim() === '') return null;
    var n = Number(String(raw).trim().replace(',', '.'));
    return Number.isFinite(n) ? n : null;
  }

  global.WwhMap = {
    STYLE_URL: STYLE_URL,
    DEFAULT_CENTER: DEFAULT_CENTER,
    VENUE_ZOOM: VENUE_ZOOM,
    loadMapLibre: loadMapLibre,
    createMap: createMap,
    setMarker: setMarker,
    openDirections: openDirections,
    googleDirectionsUrl: googleDirectionsUrl,
    googlePinUrl: googlePinUrl,
    appleMapsUrl: appleMapsUrl,
    neshanUrl: neshanUrl,
    baladUrl: baladUrl,
    isIosDevice: isIosDevice,
    parseCoord: parseCoord,
    parseMapsUrl: parseMapsUrl,
  };
})(typeof window !== 'undefined' ? window : this);
