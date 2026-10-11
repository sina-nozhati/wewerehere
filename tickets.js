/* tickets.js — renderer for the designed SVG tickets (A/B).
 *
 * THE LAYOUT IS STATIC. The ticket templates (ticket-a.svg / ticket-b.svg)
 * already contain every value slot (<text data-field="..."> / <tspan
 * data-field="...">) at its exact, final position — no runtime measuring,
 * no repositioning, no math. This script ONLY:
 *   1. injects the template (cached),
 *   2. writes the real values (name / number / code) into the slots.
 *
 * The single dynamic piece is a safety guard for unusually long names on
 * the stub: their font-size is gently reduced when they would overflow.
 * Nothing else is ever moved.
 */
(function (global) {
  'use strict';

  var TPL_CACHE = {};

  // Base for template URLs. Overridable (e.g. window.TICKET_TEMPLATE_BASE)
  // when the tickets are served from another origin (CDN, tests, previews).
  var BASE = (global.TICKET_TEMPLATE_BASE || '').replace(/\/$/, '');

  // Map every data-field slot to the matching ticket value.
  function valueFor(field, ticket) {
    if (field === 'name' || field === 'name_stub') return ticket.name;
    if (field === 'code1' || field === 'code2') return ticket.code;
    if (field === 'no1' || field === 'no2') return ticket.no;
    if (field === 'date') return ticket.date || '';
    if (field === 'time') return ticket.time || '';
    if (field === 'venue') return ticket.venue || '';
    if (field === 'city_line') {
      if (ticket.cityLine) return ticket.cityLine;
      var c = (ticket.city || '').trim();
      return c ? 'Live in ' + c : '';
    }
    return '';
  }

  function tplUrl(group) {
    return BASE + ((group === 'B' || group === 'b') ? '/ticket-b.svg' : '/ticket-a.svg');
  }

  function fetchTpl(group) {
    var url = tplUrl(group);
    if (!TPL_CACHE[url]) {
      TPL_CACHE[url] = fetch(url).then(function (r) {
        if (!r.ok) throw new Error('ticket template ' + r.status);
        return r.text();
      });
    }
    return Promise.resolve(TPL_CACHE[url]);
  }

  // Write values into slots. Positions stay exactly as designed.
  function fillValues(root, ticket) {
    root.querySelectorAll('[data-field]').forEach(function (el) {
      var field = el.getAttribute('data-field');
      var v = valueFor(field, ticket);
      el.textContent = String(v == null ? '' : v);
    });
  }

  // Long-name guard: shrink the vertical watermark name when it would overflow.
  // maxW is in the *local* user units of that name element.
  function fitNames(root) {
    var slots = root.querySelectorAll('[data-field="name"], [data-field="name_stub"]');
    if (!slots.length) return;
    slots.forEach(function (el) {
      var field = el.getAttribute('data-field');
      var style = el.getAttribute('style') || '';
      var fsMatch = style.match(/font-size:\s*([\d.]+)px/);
      var fs = fsMatch ? parseFloat(fsMatch[1]) : (parseFloat(window.getComputedStyle(el).fontSize) || 12);
      var rotated = /rotate\s*\(\s*90/.test(el.getAttribute('transform') || '');
      var maxW = field === 'name_stub' ? 72 : 80;
      if (rotated) maxW = field === 'name_stub' ? 56 : 70;
      var w = 0;
      try { w = el.getBBox().width; } catch (e) { return; }
      if (fs > 8 && w > maxW * 1.02) {
        var next = Math.max(8, (fs * maxW / w));
        var nextPx = next.toFixed(2) + 'px';
        if (style.indexOf('font-size') !== -1) {
          el.setAttribute('style', style.replace(/font-size:\s*[^;]+/, 'font-size:' + nextPx));
        } else {
          el.setAttribute('font-size', next.toFixed(2));
        }
      }
    });
  }

  // Renders a ticket into `container`. `ticket` = { group, no, code, name }.
  // Returns a Promise of the container.
  function renderTicketArt(container, ticket) {
    return fetchTpl(ticket.group).then(function (tpl) {
      container.innerHTML = tpl;
      fillValues(container, ticket);
      fitNames(container);
      return container;
    });
  }

  global.renderTicketArt = renderTicketArt;
})(typeof window !== 'undefined' ? window : globalThis);