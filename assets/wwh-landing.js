/**
 * Featured event: landing payload, capacity, marquee, setlist, sales gate.
 * Expects global: toPersian, fmtNum, escapeHtml (defined in index.html).
 */
(function () {
  var CAPACITY_POLL_MS = 45000;
  var marqueeItems = ['ما اینجا بودیم'];
  var marqueeBuilt = false;

  window.__wwhEvent = null;
  window.__wwhEventId = null;
  window.__wwhEventAt = new Date('2026-08-25T17:00:00+03:30');
  window.__wwhSalesOpen = false;
  window.__wwhPaymentInfo = null;

  function pad2(n) {
    return String(n).padStart(2, '0');
  }

  function scheduleLines(iso) {
    if (window.WwhDateTime) return window.WwhDateTime.formatHeroSchedule(iso);
    return { tagline: '', datetimeLine: '', datetimeWithSeconds: '' };
  }

  function formatFooterMeta(ev, cap) {
    if (window.WwhDateTime) return window.WwhDateTime.formatFooterMeta(ev, cap);
    return 'WE WERE HERE';
  }

  function setMarqueeTexts(texts) {
    marqueeItems = texts.filter(Boolean);
    if (!marqueeItems.length) marqueeItems = ['ما اینجا بودیم'];
    marqueeBuilt = false;
    buildMarquee();
  }

  function buildMarquee() {
    var track = document.getElementById('marquee-track');
    if (!track) return;
    var SPEED = 70;

    function itemHtml() {
      return marqueeItems
        .map(function (t) {
          return '<span class="marquee__item">' + (typeof escapeHtml === 'function' ? escapeHtml(t) : t) + '</span>';
        })
        .join('');
    }

    var probe = document.createElement('div');
    probe.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none;width:max-content;display:flex;';
    probe.innerHTML = itemHtml();
    document.body.appendChild(probe);
    var setWidth = probe.scrollWidth || 600;
    document.body.removeChild(probe);

    var copies = Math.max(2, Math.ceil((window.innerWidth * 1.5) / setWidth));
    var inner = '';
    for (var i = 0; i < copies; i++) inner += itemHtml();

    track.innerHTML =
      '<div class="marquee__group">' + inner + '</div>' +
      '<div class="marquee__group">' + inner + '</div>';

    var groupWidth = track.scrollWidth / 2;
    track.style.animationDuration = Math.max(20, groupWidth / SPEED) + 's';
    marqueeBuilt = true;
  }

  function renderSetlist(list) {
    var ol = document.getElementById('setlist-list');
    var countEl = document.getElementById('setlist-total-count');
    var timeEl = document.getElementById('setlist-total-time');
    var subtitle = document.getElementById('setlist-subtitle');
    if (!ol) return;

    if (!list || !list.length) {
      ol.innerHTML =
        '<li class="setlist__row setlist__row--empty"><span class="setlist__title">ست‌لیست به‌زودی اعلام می‌شود.</span></li>';
      if (countEl) countEl.textContent = '';
      if (timeEl) timeEl.textContent = '';
      return;
    }

    var totalSec = 0;
    ol.innerHTML = list
      .map(function (item, idx) {
        var title = item.title || item.name || '';
        var artist = item.artist || '';
        var dur = item.duration || item.time || '';
        if (dur && /^\d+:\d+$/.test(dur)) {
          var p = dur.split(':');
          totalSec += parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
        }
        return (
          '<li class="setlist__row">' +
          '<span class="setlist__no">' +
          pad2(idx + 1) +
          '</span>' +
          '<div class="setlist__info">' +
          '<span class="setlist__title">' +
          (typeof escapeHtml === 'function' ? escapeHtml(title) : title) +
          '</span>' +
          '<span class="setlist__artist">' +
          (typeof escapeHtml === 'function' ? escapeHtml(artist) : artist) +
          '</span>' +
          '</div>' +
          '<span class="setlist__end"><span class="setlist__time">' +
          (typeof escapeHtml === 'function' ? escapeHtml(dur) : dur) +
          '</span></span></li>'
        );
      })
      .join('');

    if (countEl) {
      countEl.textContent = '· ' + (typeof toPersian === 'function' ? toPersian(list.length) : list.length) + ' قطعه';
    }
    if (timeEl && totalSec > 0) {
      var m = Math.floor(totalSec / 60);
      var s = totalSec % 60;
      timeEl.textContent = pad2(m) + ':' + pad2(s);
    }
    if (subtitle) {
      subtitle.textContent =
        (typeof toPersian === 'function' ? toPersian(list.length) : list.length) +
        ' قطعه — همان ترتیبی که در اجرا پخش می‌شود.';
    }
  }

  function applySalesState(open) {
    window.__wwhSalesOpen = !!open;
    var banner = document.getElementById('sales-closed-banner');
    var regNext = document.getElementById('reg-next');
    var paySubmit = document.getElementById('pay-submit');
    var heroCta = document.getElementById('hero-register-cta');
    if (banner) banner.hidden = open;
    [regNext, paySubmit, heroCta].forEach(function (el) {
      if (!el) return;
      if (!open) {
        el.setAttribute('aria-disabled', 'true');
        if (el.tagName === 'BUTTON') el.disabled = true;
        else {
          el.classList.add('btn--disabled-link');
          el.tabIndex = -1;
        }
      } else {
        el.removeAttribute('aria-disabled');
        if (el.tagName === 'BUTTON') el.disabled = false;
        else {
          el.classList.remove('btn--disabled-link');
          el.tabIndex = 0;
        }
      }
    });
  }

  window.applyCapacity = function (remaining) {
    var rem = Math.max(0, Number(remaining) || 0);
    window.remainingTickets = rem;
    var badge = document.getElementById('capacity-badge');
    if (badge) {
      badge.classList.remove('sold-out', 'is-low');
      if (rem <= 0) {
        badge.textContent = 'ظرفیت تکمیل شد';
        badge.classList.add('sold-out');
      } else {
        var remFa = typeof toPersian === 'function' ? toPersian(rem) : rem;
        badge.textContent = remFa + ' بلیت باقی مانده';
        if (rem <= 10) badge.classList.add('is-low');
      }
    }
    var stepButtons = [document.getElementById('reg-next'), document.getElementById('pay-submit')];
    stepButtons.forEach(function (b) {
      if (!b) return;
      b.disabled = rem <= 0 || !window.__wwhSalesOpen;
    });
    if (window.__wwhEvent) {
      var sch = scheduleLines(window.__wwhEvent.eventAt);
      setMarqueeTexts([
        sch.tagline || window.__wwhEvent.title || 'ما اینجا بودیم',
        sch.datetimeLine || '',
        rem <= 0 ? 'ظرفیت تکمیل' : (typeof toPersian === 'function' ? toPersian(rem) : rem) + ' بلیت باقی مانده',
      ]);
    }
  };

  function applyEventToDom(ev, cap) {
    window.__wwhEvent = ev;
    window.__wwhEventId = ev.id;

    if (window.WwhDateTime) {
      window.WwhDateTime.applyEventScheduleToDocument(ev);
    } else {
      window.__wwhEventAt = new Date(ev.eventAt);
    }

    var footerMeta = document.getElementById('footer-meta');
    if (footerMeta) footerMeta.textContent = formatFooterMeta(ev, cap);

    if (ev.payment) {
      window.__wwhPaymentInfo = {
        cardNumber: ev.payment.cardNumber || '',
        cardHolder: ev.payment.cardHolder || '',
        bankName: ev.payment.bankName || '',
        price: ev.ticketPrice || 0,
      };
    }

    renderSetlist(ev.setlist || []);
    applySalesState(ev.salesStatus === 'open');
    var rem =
      cap && typeof cap.remaining === 'number'
        ? cap.remaining
        : ev.capacity && typeof ev.capacity === 'object' && typeof ev.capacity.remaining === 'number'
          ? ev.capacity.remaining
          : null;
    if (rem !== null) window.applyCapacity(rem);
  }

  function pollCapacity() {
    var id = window.__wwhEventId;
    var url = id ? '/api/events/' + id + '/capacity' : '/api/capacity';
    fetch(url)
      .then(function (r) {
        return r.json();
      })
      .then(function (c) {
        window.applyCapacity(c.remaining);
      })
      .catch(function () {});
  }

  function showEmptyFeatured(message) {
    var badge = document.getElementById('capacity-badge');
    if (badge) badge.textContent = message || 'به‌زودی — رویداد بعدی';
    applySalesState(false);
    renderSetlist([]);
  }

  fetch('/api/landing')
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      if (!data.featured || !data.event) {
        showEmptyFeatured(data.message);
        return;
      }
      var ev = data.event;
      var cap =
        ev.capacity && typeof ev.capacity === 'object' && ev.capacity.remaining !== undefined
          ? ev.capacity
          : null;
      applyEventToDom(ev, cap);
    })
    .catch(function () {});

  window.refreshCapacity = pollCapacity;
  setInterval(pollCapacity, CAPACITY_POLL_MS);
  setTimeout(pollCapacity, 8000);

  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(buildMarquee, 200);
  });

  if (!marqueeBuilt) buildMarquee();

  window.loadPaymentInfoFromCache = function (quantity) {
    var info = window.__wwhPaymentInfo;
    if (!info) return false;
    var num = document.getElementById('card-number');
    var holder = document.getElementById('card-holder');
    var bank = document.getElementById('card-bank');
    var price = document.getElementById('card-price');
    var priceRial = document.getElementById('card-price-rial');
    var unitPrice = document.getElementById('card-unit-price');
    var hint = document.getElementById('card-hint');
    if (!num) return false;
    if (info.cardNumber) {
      num.textContent = info.cardNumber;
      holder.textContent = info.cardHolder || '—';
      bank.textContent = info.bankName || '—';
      hint.textContent = 'بعد از واریز، رسید پرداخت رو در پایین ثبت کن.';
    } else {
      num.textContent = 'به‌زودی اعلام می‌شود';
      holder.textContent = '—';
      bank.textContent = '—';
      hint.textContent = 'برای دریافت شماره کارت با ما در تماس باش. رسید رو همین‌جا ثبت کن.';
    }
    if (info.price) {
      var total = Number(info.price) * quantity;
      price.textContent = (typeof fmtNum === 'function' ? fmtNum(total) : total) + ' تومان';
      priceRial.textContent = 'معادل ' + (typeof fmtNum === 'function' ? fmtNum(total * 10) : total * 10) + ' ریال';
      unitPrice.textContent = (typeof fmtNum === 'function' ? fmtNum(info.price) : info.price) + ' تومان';
    }
    return true;
  };
})();
