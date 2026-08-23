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
    if (field === 'name') return ticket.name;
    if (field === 'code1' || field === 'code2') return ticket.code;
    if (field === 'no1' || field === 'no2') return ticket.no;
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
      var v = valueFor(el.getAttribute('data-field'), ticket);
      el.textContent = String(v == null ? '' : v);
    });
  }

  // Long-name guard: shrink the name glyphs (font-size) only when they would
  // overflow their designed box. Layout of every other element is untouched.
  // maxW is in the *local* user units of that name element.
  function fitNames(root) {
    var slots = root.querySelectorAll('[data-field="name"]');
    if (!slots.length) return;
    slots.forEach(function (el) {
      // Stub name is font-size ~28 (scaled ~0.31); greeting name ~10 (scaled ~0.93).
      var fs = parseFloat(window.getComputedStyle(el).fontSize) || 10;
      var maxW = fs > 14 ? 190 : 62; // generous boxes; only truly long names shrink
      var w = 0;
      try { w = el.getBBox().width; } catch (e) { return; }
      if (fs > 8 && w > maxW * 1.02) {
        el.setAttribute('font-size', Math.max(8, (fs * maxW / w)).toFixed(2));
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