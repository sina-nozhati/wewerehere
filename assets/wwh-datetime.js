/**
 * Jalali / Tehran schedule formatting for landing (single source from event.eventAt).
 */
(function (global) {
  var TZ = 'Asia/Tehran';
  var ORDINALS = [
    '',
    'اول',
    'دوم',
    'سوم',
    'چهارم',
    'پنجم',
    'ششم',
    'هفتم',
    'هشتم',
    'نهم',
    'دهم',
    'یازدهم',
    'دوازدهم',
    'سیزدهم',
    'چهاردهم',
    'پانزدهم',
    'شانزدهم',
    'هفدهم',
    'هجدهم',
    'نوزدهم',
    'بیستم',
    'بیست‌و‌یکم',
    'بیست‌و‌دوم',
    'بیست‌و‌سوم',
    'بیست‌و‌چهارم',
    'بیست‌و‌پنجم',
    'بیست‌و‌ششم',
    'بیست‌و‌هفتم',
    'بیست‌و‌هشتم',
    'بیست‌و‌نهم',
    'سی‌ام',
    'سی‌و‌یکم',
  ];

  function parseEventDate(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    return isNaN(d.getTime()) ? null : d;
  }

  function formatJalaliParts(date) {
    var fmt = new Intl.DateTimeFormat('fa-IR-u-ca-persian', {
      timeZone: TZ,
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
    var parts = fmt.formatToParts(date);
    var out = { year: '', month: '', day: '', hour: '', minute: '', second: '' };
    parts.forEach(function (p) {
      if (p.type in out) out[p.type] = p.value;
    });
    out.dayLatin = out.day.replace(/[۰-۹]/g, function (c) {
      return '۰۱۲۳۴۵۶۷۸۹'.indexOf(c);
    });
    out.dayNum = parseInt(out.dayLatin, 10) || 0;
    return out;
  }

  function formatOrdinalDayFa(dayNum) {
    if (dayNum >= 1 && dayNum < ORDINALS.length) return ORDINALS[dayNum];
    return String(dayNum);
  }

  function toPersianDigits(str) {
    if (typeof global.toPersian === 'function') return global.toPersian(str);
    return String(str).replace(/\d/g, function (d) {
      return '۰۱۲۳۴۵۶۷۸۹'[d];
    });
  }

  function formatHeroSchedule(iso) {
    var date = parseEventDate(iso);
    if (!date) {
      return {
        tagline: '',
        datetimeLine: '',
        datetimeWithSeconds: '',
        timeHm: '',
        eventDate: null,
      };
    }
    var p = formatJalaliParts(date);
    var ordinal = formatOrdinalDayFa(p.dayNum);
    var tagline = ordinal && p.month ? ordinal + ' ' + p.month : p.month || '';
    var timeHm = toPersianDigits(p.hour) + ':' + toPersianDigits(p.minute);
    var timeHms = timeHm + ':' + toPersianDigits(p.second);
    var datetimeLine =
      toPersianDigits(p.day) + ' ' + p.month + ' ' + toPersianDigits(p.year) + '، ساعت ' + timeHm;
    var datetimeWithSeconds = datetimeLine + ':' + toPersianDigits(p.second);

    return {
      tagline: tagline,
      datetimeLine: datetimeLine,
      datetimeWithSeconds: datetimeWithSeconds,
      timeHm: timeHm,
      eventDate: date,
    };
  }

  function buildHeroSubline(sched, ev) {
    var parts = [];
    if (sched && sched.timeHm) parts.push('ساعت ' + sched.timeHm);
    var loc = [];
    if (ev && ev.city) loc.push(ev.city);
    if (ev && ev.venue) loc.push(ev.venue);
    if (loc.length) parts.push(loc.join(' · '));
    return parts.join(' · ') || sched.datetimeLine || '';
  }

  function applyEventScheduleToDocument(ev) {
    if (!ev || !ev.eventAt) return null;
    var sched = formatHeroSchedule(ev.eventAt);
    var tagEl = document.getElementById('hero-jalali-tagline');
    if (tagEl && sched.tagline) tagEl.textContent = sched.tagline;
    var dateEl = document.getElementById('hero-date');
    if (dateEl) {
      dateEl.textContent = buildHeroSubline(sched, ev);
    }
    var titleEl = document.getElementById('hero-event-title');
    if (titleEl) {
      if (ev.episodeNumber) {
        titleEl.textContent =
          'اپیزود ' +
          (typeof global.toPersian === 'function' ? global.toPersian(ev.episodeNumber) : ev.episodeNumber);
        titleEl.hidden = false;
      } else {
        titleEl.hidden = true;
        titleEl.textContent = '';
      }
    }
    var cityEl = document.getElementById('hero-city');
    var venueEl = document.getElementById('hero-venue');
    var locWrap = document.getElementById('hero-location');
    if (cityEl) cityEl.textContent = ev.city || '';
    if (venueEl) venueEl.textContent = ev.venue || '';
    if (locWrap) {
      locWrap.textContent = [ev.city, ev.venue].filter(Boolean).join(' · ');
      locWrap.hidden = !(ev.city || ev.venue);
    }
    if (ev.title) {
      document.title = ev.title + ' — WE WERE HERE';
      var meta = document.querySelector('meta[name="description"]');
      if (meta && sched.tagline) {
        meta.setAttribute(
          'content',
          ev.title + ' — ' + sched.tagline + '. ثبت‌نام و دریافت بلیط.'
        );
      }
    }
    global.__wwhEventAt = sched.eventDate;
    try {
      global.dispatchEvent(new CustomEvent('wwh:event-ready', { detail: { event: ev, schedule: sched } }));
    } catch (e) {
      /* IE not supported */
    }
    return sched;
  }

  function formatFooterMeta(ev, cap) {
    var sched = formatHeroSchedule(ev.eventAt);
    var parts = [];
    if (ev.episodeNumber) {
      parts.push(
        'اپیزود ' +
          (typeof global.toPersian === 'function' ? global.toPersian(ev.episodeNumber) : ev.episodeNumber)
      );
    }
    if (sched.datetimeLine) parts.push(sched.datetimeLine);
    if (cap && typeof cap.remaining === 'number') {
      var rem = cap.remaining;
      parts.push(
        rem <= 0
          ? 'ظرفیت تکمیل'
          : 'ظرفیت ' + (typeof global.toPersian === 'function' ? global.toPersian(rem) : rem) + ' بلیط'
      );
    }
    return parts.join(' — ') || 'WE WERE HERE';
  }

  global.WwhDateTime = {
    parseEventDate: parseEventDate,
    formatHeroSchedule: formatHeroSchedule,
    applyEventScheduleToDocument: applyEventScheduleToDocument,
    formatFooterMeta: formatFooterMeta,
  };
})(typeof window !== 'undefined' ? window : globalThis);
