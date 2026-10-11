/**
 * Iran mobile: 09123456789 (11 digits). Shared across site forms.
 */
(function (global) {
  'use strict';

  var FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
  var AR_DIGITS = '٠١٢٣٤٥٦٧٨٩';
  var COMPLETE_RE = /^09\d{9}$/;
  var INVALID_HINT = 'شماره باید دقیقاً به صورت 09123456789 (۱۱ رقم) باشد.';

  function normalizeDigits(s) {
    return String(s)
      .replace(/[۰-۹]/g, function (d) { return String(FA_DIGITS.indexOf(d)); })
      .replace(/[٠-٩]/g, function (d) { return String(AR_DIGITS.indexOf(d)); });
  }

  /** Live input: digits only, max 11, must stay a valid prefix of 09xxxxxxxxx */
  function sanitizeIranMobilePartial(raw) {
    var d = normalizeDigits(raw).replace(/\D/g, '');
    if (!d) return '';
    if (d.charAt(0) !== '0') {
      if (d.charAt(0) === '9' && d.length <= 10) {
        d = '0' + d;
      } else {
        return '';
      }
    }
    if (d.length >= 2 && d.charAt(1) !== '9') {
      return d.charAt(0);
    }
    return d.slice(0, 11);
  }

  function parseIranMobile(raw) {
    var d = sanitizeIranMobilePartial(raw);
    return COMPLETE_RE.test(d) ? d : '';
  }

  function isCompleteIranMobile(raw) {
    return COMPLETE_RE.test(sanitizeIranMobilePartial(raw));
  }

  function bindIranMobileInput(input) {
    if (!input || input.__wwhPhoneBound) return;
    input.__wwhPhoneBound = true;
    input.setAttribute('maxlength', '11');
    input.setAttribute('inputmode', 'numeric');
    input.setAttribute('pattern', '09[0-9]{9}');
    input.setAttribute('autocomplete', 'tel');

    function apply() {
      var next = sanitizeIranMobilePartial(input.value);
      if (input.value !== next) input.value = next;
    }

    input.addEventListener('input', apply);
    input.addEventListener('paste', function (e) {
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData('text');
      input.value = sanitizeIranMobilePartial(text);
    });
    apply();
  }

  function bindAllIranMobileInputs(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('[data-wwh-phone]').forEach(bindIranMobileInput);
  }

  global.WwhPhone = {
    normalizeDigits: normalizeDigits,
    sanitizeIranMobilePartial: sanitizeIranMobilePartial,
    parseIranMobile: parseIranMobile,
    isCompleteIranMobile: isCompleteIranMobile,
    bindIranMobileInput: bindIranMobileInput,
    bindAllIranMobileInputs: bindAllIranMobileInputs,
    INVALID_HINT: INVALID_HINT,
    COMPLETE_RE: COMPLETE_RE
  };
})(typeof window !== 'undefined' ? window : globalThis);
