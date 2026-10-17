/**
 * WwhUploader — sequential multipart queue with pause / resume / cancel / offline.
 * Soft pause: completed files stay; current file restarts from byte 0 on resume.
 */
(function (global) {
  'use strict';

  var FA = '۰۱۲۳۴۵۶۷۸۹';
  function defaultToFa(s) {
    return String(s).replace(/\d/g, function (d) { return FA[d]; });
  }

  function formatBytes(n) {
    n = Number(n) || 0;
    if (n < 1024) return Math.round(n) + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(2) + ' MB';
  }

  function formatSpeed(bps) {
    if (!bps || bps < 1) return '—';
    return formatBytes(bps) + '/s';
  }

  var STATUS_LABEL = {
    waiting: 'در صف',
    uploading: 'در حال آپلود',
    paused: 'مکث',
    done: 'انجام شد',
    error: 'خطا',
    cancelled: 'لغو شد'
  };

  function WwhUploader(opts) {
    opts = opts || {};
    this.opts = opts;
    this.root = typeof opts.root === 'string' ? document.querySelector(opts.root) : opts.root;
    if (!this.root) throw new Error('WwhUploader: root required');
    this.toFa = opts.toFa || defaultToFa;
    this.accept = opts.accept || 'image/*,video/*';
    this.multiple = opts.multiple !== false;
    this.showCaption = opts.showCaption !== false;
    this.queue = [];
    this.index = 0;
    this.gen = 0;
    this.xhr = null;
    this.state = 'idle';
    this._speed = 0;
    this._lastLoaded = 0;
    this._lastTs = 0;
    this._offlinePaused = false;
    this._build();
    this._bindNet();
  }

  WwhUploader.prototype._build = function () {
    var root = this.root;
    root.classList.add('wwh-up');
    root.innerHTML =
      '<div class="wwh-up__drop" tabindex="0" role="button" aria-label="انتخاب فایل">' +
        '<div class="wwh-up__drop-title">فایل‌ها را اینجا رها کن یا انتخاب کن</div>' +
        '<div class="wwh-up__drop-hint">عکس و ویدیو — چند فایل مجاز است</div>' +
      '</div>' +
      '<input type="file" class="wwh-up__file" ' + (this.multiple ? 'multiple ' : '') +
        'accept="' + this.accept.replace(/"/g, '') + '">' +
      (this.showCaption
        ? '<div class="wwh-up__caption"><label><span class="wwh-up__cap-label">توضیح (اختیاری)</span>' +
          '<input type="text" class="wwh-up__cap-input" maxlength="500" placeholder="مثلاً: پشت‌صحنه"></label></div>'
        : '') +
      '<div class="wwh-up__summary" aria-live="polite"></div>' +
      '<div class="wwh-up__overall" hidden><div class="wwh-up__overall-bar"></div></div>' +
      '<ul class="wwh-up__list" hidden></ul>' +
      '<div class="wwh-up__controls" hidden>' +
        '<button type="button" class="wwh-up__btn wwh-up__btn--primary" data-act="start">شروع آپلود</button>' +
        '<button type="button" class="wwh-up__btn wwh-up__btn--ghost" data-act="pause" hidden>مکث</button>' +
        '<button type="button" class="wwh-up__btn wwh-up__btn--primary" data-act="resume" hidden>ادامه</button>' +
        '<button type="button" class="wwh-up__btn wwh-up__btn--danger" data-act="cancel" hidden>لغو همه</button>' +
        '<button type="button" class="wwh-up__btn wwh-up__btn--ghost" data-act="retry" hidden>تلاش مجدد</button>' +
      '</div>' +
      '<p class="wwh-up__status" role="status" aria-live="polite"></p>';

    this.els = {
      drop: root.querySelector('.wwh-up__drop'),
      file: root.querySelector('.wwh-up__file'),
      cap: root.querySelector('.wwh-up__cap-input'),
      summary: root.querySelector('.wwh-up__summary'),
      overall: root.querySelector('.wwh-up__overall'),
      overallBar: root.querySelector('.wwh-up__overall-bar'),
      list: root.querySelector('.wwh-up__list'),
      controls: root.querySelector('.wwh-up__controls'),
      start: root.querySelector('[data-act="start"]'),
      pause: root.querySelector('[data-act="pause"]'),
      resume: root.querySelector('[data-act="resume"]'),
      cancel: root.querySelector('[data-act="cancel"]'),
      retry: root.querySelector('[data-act="retry"]'),
      status: root.querySelector('.wwh-up__status')
    };

    var self = this;
    this.els.drop.addEventListener('click', function () { self.els.file.click(); });
    this.els.drop.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); self.els.file.click(); }
    });
    this.els.file.addEventListener('change', function () {
      if (self.els.file.files && self.els.file.files.length) {
        self.addFiles(self.els.file.files);
        self.els.file.value = '';
      }
    });
    ['dragenter', 'dragover'].forEach(function (ev) {
      self.els.drop.addEventListener(ev, function (e) {
        e.preventDefault();
        e.stopPropagation();
        self.els.drop.classList.add('is-drag');
      });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      self.els.drop.addEventListener(ev, function (e) {
        e.preventDefault();
        e.stopPropagation();
        self.els.drop.classList.remove('is-drag');
        if (ev === 'drop' && e.dataTransfer && e.dataTransfer.files) {
          self.addFiles(e.dataTransfer.files);
        }
      });
    });
    this.els.start.addEventListener('click', function () { self.start(); });
    this.els.pause.addEventListener('click', function () { self.pause('manual'); });
    this.els.resume.addEventListener('click', function () { self.resume(); });
    this.els.cancel.addEventListener('click', function () { self.cancelAll(); });
    this.els.retry.addEventListener('click', function () { self.resume(); });
  };

  WwhUploader.prototype._bindNet = function () {
    var self = this;
    this._onOffline = function () {
      if (self.state === 'uploading') {
        self._offlinePaused = true;
        self.pause('offline');
      }
    };
    this._onOnline = function () {
      if (self._offlinePaused && self.state === 'paused') {
        self._setStatus('اتصال برگشت — برای ادامه بزن «ادامه».', 'warn');
      }
    };
    window.addEventListener('offline', this._onOffline);
    window.addEventListener('online', this._onOnline);
  };

  WwhUploader.prototype.destroy = function () {
    window.removeEventListener('offline', this._onOffline);
    window.removeEventListener('online', this._onOnline);
    this.cancelAll();
  };

  WwhUploader.prototype.getCaption = function () {
    return this.els.cap ? String(this.els.cap.value || '').trim() : '';
  };

  WwhUploader.prototype.addFiles = function (fileList, opts) {
    opts = opts || {};
    if (this.state === 'uploading') {
      this._setStatus('اول آپلود جاری را مکث یا لغو کن.', 'err');
      return;
    }
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    if (typeof this.opts.filterFiles === 'function') {
      files = this.opts.filterFiles(files) || [];
    }
    if (!files.length) return;

    var newItems = files.map(function (f) {
      return {
        file: f,
        name: f.name || 'file',
        size: f.size || 0,
        loaded: 0,
        status: 'waiting',
        error: ''
      };
    });
    // Append by default so successive camera shots accumulate in the queue.
    var replace = !!opts.replace;
    if (replace || !this.queue.length) {
      this.queue = newItems;
      this.index = 0;
    } else {
      // Drop finished/cancelled items when starting a fresh batch after a completed run
      if (this.state === 'done' || this.state === 'cancelled') {
        this.queue = this.queue.filter(function (it) {
          return it.status === 'waiting' || it.status === 'error' || it.status === 'paused';
        });
        this.index = 0;
      }
      this.queue = this.queue.concat(newItems);
    }
    this.state = 'queued';
    this._offlinePaused = false;
    this._renderList();
    this._updateChrome();
    this._setStatus(this.toFa(this.queue.length) + ' فایل در صف آپلود.', '');
    if (this.opts.autoStart) this.start();
  };

  WwhUploader.prototype.start = function () {
    if (!this.queue.length) {
      this._setStatus('اول فایل انتخاب کن.', 'err');
      return;
    }
    if (this.state === 'uploading') return;
    if (!navigator.onLine) {
      this._setStatus('آفلاین هستی — بعد از اتصال دوباره امتحان کن.', 'err');
      return;
    }
    this._offlinePaused = false;
    this.gen++;
    this.state = 'uploading';
    this._setStatus('', '');
    this._updateChrome();
    this._pump();
  };

  WwhUploader.prototype.pause = function (reason) {
    if (this.state !== 'uploading') return;
    this.gen++;
    this.state = 'paused';
    if (this.xhr) {
      try { this.xhr.abort(); } catch (e) { /* ignore */ }
      this.xhr = null;
    }
    var cur = this.queue[this.index];
    if (cur && cur.status === 'uploading') {
      cur.status = 'paused';
      cur.loaded = 0;
    }
    this._renderList();
    this._updateChrome();
    if (reason === 'offline') {
      this._setStatus('اتصال قطع شد — آپلود مکث شد.', 'warn');
    } else {
      this._setStatus('مکث شد. با «ادامه» از همین فایل دوباره شروع می‌شود.', 'warn');
    }
    if (typeof this.opts.onPause === 'function') this.opts.onPause(reason);
  };

  WwhUploader.prototype.resume = function () {
    if (this.state !== 'paused' && this.state !== 'failed') return;
    this._offlinePaused = false;
    var cur = this.queue[this.index];
    if (cur && (cur.status === 'paused' || cur.status === 'error' || cur.status === 'cancelled')) {
      cur.status = 'waiting';
      cur.loaded = 0;
      cur.error = '';
    }
    this.start();
  };

  WwhUploader.prototype.cancelAll = function () {
    this.gen++;
    if (this.xhr) {
      try { this.xhr.abort(); } catch (e) { /* ignore */ }
      this.xhr = null;
    }
    var had = this.queue.length > 0;
    for (var i = this.index; i < this.queue.length; i++) {
      if (this.queue[i].status !== 'done') {
        this.queue[i].status = 'cancelled';
        this.queue[i].loaded = 0;
      }
    }
    this.queue = [];
    this.index = 0;
    this.state = 'idle';
    this._renderList();
    this._updateChrome();
    if (had) this._setStatus('آپلود لغو شد.', 'err');
    else this._setStatus('', '');
    if (typeof this.opts.onCancel === 'function') this.opts.onCancel();
  };

  WwhUploader.prototype._pump = function () {
    if (this.state !== 'uploading') return;
    while (this.index < this.queue.length && this.queue[this.index].status === 'done') {
      this.index++;
    }
    if (this.index >= this.queue.length) {
      this._finishOk();
      return;
    }
    this._sendCurrent();
  };

  WwhUploader.prototype._sendCurrent = function () {
    var self = this;
    var gen = this.gen;
    var item = this.queue[this.index];
    item.status = 'uploading';
    item.loaded = 0;
    item.error = '';
    this._speed = 0;
    this._lastLoaded = 0;
    this._lastTs = 0;
    this._renderList();
    this._updateChrome();

    var fd;
    try {
      fd = this.opts.buildFormData(item.file, {
        caption: this.getCaption(),
        index: this.index,
        total: this.queue.length
      });
    } catch (err) {
      this._failItem(String(err && err.message ? err.message : err));
      return;
    }
    if (!(fd instanceof FormData)) {
      this._failItem('buildFormData باید FormData برگرداند.');
      return;
    }

    var url = typeof this.opts.getUrl === 'function'
      ? this.opts.getUrl(item.file)
      : this.opts.url;
    if (!url) {
      this._failItem('آدرس آپلود مشخص نیست.');
      return;
    }

    var xhr = new XMLHttpRequest();
    this.xhr = xhr;
    xhr.open('POST', url);
    var headers = {};
    if (typeof this.opts.getHeaders === 'function') {
      headers = this.opts.getHeaders() || {};
    }
    Object.keys(headers).forEach(function (k) {
      if (headers[k] != null) xhr.setRequestHeader(k, headers[k]);
    });

    xhr.upload.onprogress = function (e) {
      if (gen !== self.gen) return;
      if (!e.lengthComputable) return;
      var now = e.timeStamp || Date.now();
      var loaded = e.loaded;
      if (self._lastTs && now > self._lastTs) {
        var inst = ((loaded - self._lastLoaded) * 1000) / (now - self._lastTs);
        self._speed = self._speed ? self._speed * 0.7 + inst * 0.3 : inst;
      }
      self._lastLoaded = loaded;
      self._lastTs = now;
      item.loaded = loaded;
      self._renderItem(self.index);
      self._updateSummary();
    };

    xhr.onload = function () {
      if (gen !== self.gen) return;
      self.xhr = null;
      var ok = xhr.status >= 200 && xhr.status < 300;
      var json = null;
      try { json = JSON.parse(xhr.responseText || '{}'); } catch (e) { json = null; }
      if (ok) {
        var validateMsg = null;
        if (typeof self.opts.validateResponse === 'function') {
          try { validateMsg = self.opts.validateResponse(json, xhr, item); } catch (e3) {
            validateMsg = String(e3 && e3.message ? e3.message : e3);
          }
        }
        if (validateMsg) {
          self._failItem(validateMsg);
          return;
        }
        item.status = 'done';
        item.loaded = item.size;
        self._renderItem(self.index);
        if (typeof self.opts.onItemSuccess === 'function') {
          try { self.opts.onItemSuccess(item, json, xhr); } catch (e2) { /* ignore */ }
        }
        self.index++;
        self._pump();
      } else {
        var msg = 'خطای سرور (' + xhr.status + ')';
        if (json) {
          if (typeof json.error === 'string') msg = json.error;
          else if (json.detail && typeof json.detail === 'object' && json.detail.error) msg = json.detail.error;
          else if (typeof json.detail === 'string') msg = json.detail;
          else if (json.message) msg = json.message;
        }
        if (xhr.status === 401 && typeof self.opts.onUnauthorized === 'function') {
          self.opts.onUnauthorized();
        }
        self._failItem(msg);
      }
    };
    xhr.onerror = function () {
      if (gen !== self.gen) return;
      self.xhr = null;
      if (!navigator.onLine) {
        self._offlinePaused = true;
        self.pause('offline');
        return;
      }
      self._failItem('خطای اتصال. اینترنتت را چک کن.');
    };
    xhr.onabort = function () {
      if (gen !== self.gen) return;
      self.xhr = null;
      // pause/cancel already set state
    };
    xhr.send(fd);
  };

  WwhUploader.prototype._failItem = function (message) {
    var item = this.queue[this.index];
    if (item) {
      item.status = 'error';
      item.error = message;
      item.loaded = 0;
    }
    this.state = 'failed';
    this.xhr = null;
    this._renderList();
    this._updateChrome();
    this._setStatus('خطا در «' + (item ? item.name : '') + '»: ' + message, 'err');
    if (typeof this.opts.onItemError === 'function') this.opts.onItemError(item, message);
  };

  WwhUploader.prototype._finishOk = function () {
    this.state = 'done';
    this.xhr = null;
    this._renderList();
    this._updateChrome();
    var done = this.queue.filter(function (i) { return i.status === 'done'; }).length;
    this._setStatus('آپلود شد: ' + this.toFa(done) + ' فایل.', 'ok');
    if (this.els.cap) this.els.cap.value = '';
    if (typeof this.opts.onQueueDone === 'function') {
      this.opts.onQueueDone({ done: done, total: this.queue.length });
    }
  };

  WwhUploader.prototype._doneCount = function () {
    return this.queue.filter(function (i) { return i.status === 'done'; }).length;
  };

  WwhUploader.prototype._overallPct = function () {
    if (!this.queue.length) return 0;
    var total = 0;
    var loaded = 0;
    for (var i = 0; i < this.queue.length; i++) {
      var it = this.queue[i];
      total += it.size || 1;
      if (it.status === 'done') loaded += it.size || 1;
      else if (it.status === 'uploading') loaded += Math.min(it.loaded || 0, it.size || 0);
    }
    return total ? Math.round((loaded * 100) / total) : 0;
  };

  WwhUploader.prototype._updateSummary = function () {
    var n = this.queue.length;
    if (!n) {
      this.els.summary.textContent = '';
      this.els.overall.hidden = true;
      return;
    }
    var cur = Math.min(this.index + 1, n);
    if (this.state === 'done') cur = n;
    var done = this._doneCount();
    var item = this.queue[Math.min(this.index, n - 1)];
    var parts = [
      '<strong>' + this.toFa(done) + '</strong> از <strong>' + this.toFa(n) + '</strong> تمام'
    ];
    if (this.state === 'uploading' && item) {
      parts.push('— فایل <strong>' + this.toFa(cur) + '</strong> از <strong>' + this.toFa(n) + '</strong>');
      parts.push('· ' + this.toFa(Math.round(((item.loaded || 0) / (item.size || 1)) * 100)) + '٪');
      parts.push('· ' + formatBytes(item.loaded) + ' / ' + formatBytes(item.size));
      parts.push('· ' + formatSpeed(this._speed));
    }
    this.els.summary.innerHTML = parts.join(' ');
    this.els.overall.hidden = false;
    var pct = this._overallPct();
    this.els.overallBar.style.width = pct + '%';
    this.els.overallBar.classList.toggle('is-done', this.state === 'done');
  };

  WwhUploader.prototype._updateChrome = function () {
    var has = this.queue.length > 0;
    this.els.list.hidden = !has;
    this.els.controls.hidden = !has;
    var uploading = this.state === 'uploading';
    var paused = this.state === 'paused';
    var failed = this.state === 'failed';
    var idleish = this.state === 'idle' || this.state === 'queued' || this.state === 'done';
    this.els.start.hidden = !(idleish && has && this.state !== 'done');
    if (this.state === 'done') this.els.start.hidden = true;
    this.els.pause.hidden = !uploading;
    this.els.resume.hidden = !(paused || failed);
    this.els.cancel.hidden = !(uploading || paused || failed);
    this.els.retry.hidden = !failed;
    this.els.drop.style.pointerEvents = uploading ? 'none' : '';
    this.els.drop.style.opacity = uploading ? '0.55' : '';
    this._updateSummary();
  };

  WwhUploader.prototype._renderList = function () {
    var self = this;
    this.els.list.innerHTML = this.queue.map(function (item, i) {
      return self._itemHtml(item, i);
    }).join('');
  };

  WwhUploader.prototype._renderItem = function (i) {
    var li = this.els.list.children[i];
    if (!li) {
      this._renderList();
      return;
    }
    var tmp = document.createElement('ul');
    tmp.innerHTML = this._itemHtml(this.queue[i], i);
    li.replaceWith(tmp.firstChild);
    this._updateSummary();
  };

  WwhUploader.prototype._itemHtml = function (item, i) {
    var pct = item.size ? Math.min(100, Math.round((item.loaded / item.size) * 100)) : (item.status === 'done' ? 100 : 0);
    if (item.status === 'done') pct = 100;
    var meta = formatBytes(item.loaded) + ' / ' + formatBytes(item.size);
    if (item.status === 'uploading') meta += ' · ' + formatSpeed(this._speed);
    if (item.status === 'error' && item.error) meta = item.error;
    return (
      '<li class="wwh-up__item is-' + item.status + '" data-i="' + i + '">' +
        '<div class="wwh-up__item-top">' +
          '<span class="wwh-up__name">' + escapeHtml(item.name) + '</span>' +
          '<span class="wwh-up__badge">' + (STATUS_LABEL[item.status] || item.status) +
            (item.status === 'uploading' || item.status === 'done' ? ' · ' + this.toFa(pct) + '٪' : '') +
          '</span>' +
        '</div>' +
        '<div class="wwh-up__track"><div class="wwh-up__bar" style="width:' + pct + '%"></div></div>' +
        '<div class="wwh-up__meta">' + escapeHtml(meta) + '</div>' +
      '</li>'
    );
  };

  WwhUploader.prototype._setStatus = function (msg, kind) {
    this.els.status.textContent = msg || '';
    this.els.status.className = 'wwh-up__status' +
      (kind === 'ok' ? ' is-ok' : kind === 'err' ? ' is-err' : kind === 'warn' ? ' is-warn' : '');
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  global.WwhUploader = WwhUploader;
})(typeof window !== 'undefined' ? window : this);
