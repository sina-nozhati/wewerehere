/**
 * Parse FastAPI / JSON error bodies for user-visible messages.
 */
(function (global) {
  'use strict';

  function errorMessage(body, fallback) {
    fallback = fallback == null ? '' : String(fallback);
    if (body == null || body === '') return fallback;
    if (typeof body === 'string') return body;
    if (typeof body.message === 'string' && body.message) return body.message;
    if (typeof body.error === 'string' && body.error) return body.error;
    var d = body.detail;
    if (typeof d === 'string' && d) return d;
    if (d && typeof d === 'object' && !Array.isArray(d)) {
      if (typeof d.detail === 'string' && d.detail) return d.detail;
      if (typeof d.message === 'string' && d.message) return d.message;
      if (typeof d.error === 'string' && d.error) return d.error;
    }
    if (Array.isArray(d)) {
      var parts = d.map(function (x) {
        return x && (x.msg || x.message) ? String(x.msg || x.message) : '';
      }).filter(Boolean);
      if (parts.length) return parts.join('؛ ');
    }
    return fallback;
  }

  global.WwhApi = global.WwhApi || {};
  global.WwhApi.errorMessage = errorMessage;
})(typeof window !== 'undefined' ? window : globalThis);
