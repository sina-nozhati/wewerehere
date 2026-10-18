/**
 * WwhUploader — sequential multipart queue with pause / resume / cancel / offline.
 * Soft pause: completed files stay; current file restarts from byte 0 on resume.
 * Action chrome: one primary CTA + contextual secondaries (no duplicate retry/resume).
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

  var BUSY_STATES = { uploading: 1, paused: 1, failed: 1 };

  function WwhUploader(opts) {
    opts = opts || {};
    this.opts = opts;
    this.root = typeof opts.root === 'string' ? document.querySelector(opts.root) : opts.root;
    if (!this.root) throw new Error('WwhUploader: root required');
    this.toFa = opts.toFa || defaultToFa;
    this.accept = opts.accept || 'image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif,video/mp4,video/webm,video/quicktime,.jpg,.jpeg,.png,.webp,.heic,.heif,.avif,.mp4,.webm,.mov,.m4v';
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
        '<div class="wwh-up__drop-hint">عکس (JPG/PNG/HEIC) و ویدیو (MP4/MOV) — چند فایل مجاز است</div>' +
      '</div>' +
      '<input type="file" class="wwh-up__file" ' + (this.multiple ? 'multiple ' : '') +
        'accept="' + this.accept.replace(/"/g, '') + '">' +
      (this.showCaption
        ? '<div class="wwh-up__caption"><label><span class="wwh-up__cap-label">توضیح (اختیاری)</span>' +
          '<input type="text" class="wwh-up__cap-input" maxlength="500" placeholder="مثلاً: پشت‌صحنه"></label></div>'
        : '') +
      '<div class="wwh-up__summary" role="status" aria-live="polite" aria-atomic="true"></div>' +
      '<div class="wwh-up__overall" hidden><div class="wwh-up__overall-bar"></div></div>' +
      '<ul class="wwh-up__list" hidden aria-label="فایل‌های در صف"></ul>' +
      '<div class="wwh-up__controls" hidden>' +
        '<div class="wwh-up__primary-row">' +
          '<button type="button" class="wwh-up__btn wwh-up__btn--primary" data-act="primary" hidden>شروع آپلود</button>' +
        '</div>' +
        '<div class="wwh-up__secondary-row">' +
          '<button type="button" class="wwh-up__btn wwh-up__btn--ghost" data-act="pause" hidden>مکث</button>' +
          '<button type="button" class="wwh-up__btn wwh-up__btn--ghost" data-act="clear" hidden>پاک کردن صف</button>' +
          '<button type="button" class="wwh-up__btn wwh-up__btn--danger" data-act="cancel" hidden>لغو همه</button>' +
        '</div>' +
      '</div>' +
      '<p class="wwh-up__status" role="status" aria-live="polite"></p>' +
      '<div class="wwh-up__lightbox" hidden role="dialog" aria-modal="true" aria-label="پیش‌نمایش">' +
        '<button type="button" class="wwh-up__lightbox-close" data-lb-close aria-label="بستن">×</button>' +
        '<div class="wwh-up__lightbox-body"></div>' +
      '</div>';

    this.els = {
      drop: root.querySelector('.wwh-up__drop'),
      file: root.querySelector('.wwh-up__file'),
      cap: root.querySelector('.wwh-up__cap-input'),
      summary: root.querySelector('.wwh-up__summary'),
      overall: root.querySelector('.wwh-up__overall'),
      overallBar: root.querySelector('.wwh-up__overall-bar'),
      list: root.querySelector('.wwh-up__list'),
      controls: root.querySelector('.wwh-up__controls'),
      primary: root.querySelector('[data-act="primary"]'),
      pause: root.querySelector('[data-act="pause"]'),
      clear: root.querySelector('[data-act="clear"]'),
      cancel: root.querySelector('[data-act="cancel"]'),
      status: root.querySelector('.wwh-up__status'),
      lightbox: root.querySelector('.wwh-up__lightbox'),
      lightboxBody: root.querySelector('.wwh-up__lightbox-body')
    };

    var self = this;
    this.els.drop.addEventListener('click', function () {
      if (BUSY_STATES[self.state]) return;
      self.els.file.click();
    });
    this.els.drop.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (BUSY_STATES[self.state]) return;
        self.els.file.click();
      }
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
        if (BUSY_STATES[self.state]) return;
        self.els.drop.classList.add('is-drag');
      });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      self.els.drop.addEventListener(ev, function (e) {
        e.preventDefault();
        e.stopPropagation();
        self.els.drop.classList.remove('is-drag');
        if (ev === 'drop' && e.dataTransfer && e.dataTransfer.files) {
          if (BUSY_STATES[self.state]) {
            self._setStatus('اول آپلود جاری را مکث یا لغو کن.', 'err');
            return;
          }
          self.addFiles(e.dataTransfer.files);
        }
      });
    });
    this.els.primary.addEventListener('click', function () {
      if (self.state === 'paused' || self.state === 'failed') self.resume();
      else if (self.state === 'done') self.addMore();
      else self.start();
    });
    this.els.pause.addEventListener('click', function () { self.pause('manual'); });
    this.els.clear.addEventListener('click', function () { self.clearQueue(); });
    this.els.cancel.addEventListener('click', function () { self.cancelAll(); });
    this.els.list.addEventListener('click', function (e) {
      var rem = e.target.closest('[data-remove]');
      if (rem) {
        e.preventDefault();
        e.stopPropagation();
        var ri = parseInt(rem.getAttribute('data-remove'), 10);
        if (!isNaN(ri)) self.removeAt(ri);
        return;
      }
      var view = e.target.closest('[data-view]');
      if (view) {
        e.preventDefault();
        var vi = parseInt(view.getAttribute('data-view'), 10);
        if (!isNaN(vi)) self.openPreview(vi);
      }
    });
    this.els.list.addEventListener(
      'wheel',
      function (e) {
        self._onListWheel(e);
      },
      { passive: false }
    );
    this.els.lightbox.addEventListener('click', function (e) {
      if (e.target === self.els.lightbox || e.target.closest('[data-lb-close]')) {
        self.closePreview();
      }
    });
    this._onLbKey = function (e) {
      if (e.key === 'Escape' && self.els.lightbox && !self.els.lightbox.hidden) {
        self.closePreview();
      }
    };
    document.addEventListener('keydown', this._onLbKey);
    this._onListResize = function () { self._syncListScrollable(); };
    window.addEventListener('resize', this._onListResize, { passive: true });
  };

  WwhUploader.prototype._syncListScrollable = function () {
    var list = this.els && this.els.list;
    if (!list || list.hidden) return;
    list.classList.remove('is-scrollable');
    /* Measure natural height; only cap when content would exceed 420px */
    var needs = list.scrollHeight > 420 + 1;
    list.classList.toggle('is-scrollable', needs);
  };

  WwhUploader.prototype._onListWheel = function (e) {
    var list = this.els.list;
    if (!list || !list.classList.contains('is-scrollable')) {
      /* Let the page scroll — do not trap */
      return;
    }
    var dy = e.deltaY;
    if (!dy) return;
    var atTop = list.scrollTop <= 0;
    var atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 1;
    if ((dy < 0 && atTop) || (dy > 0 && atBottom)) {
      /* Propagate to window so the page continues scrolling */
      window.scrollBy({ top: dy, left: 0, behavior: 'auto' });
      e.preventDefault();
    }
  };

  WwhUploader.prototype._isVideo = function (file) {
    if (!file) return false;
    if (file.type && file.type.indexOf('video/') === 0) return true;
    return /\.(mp4|webm|mov|m4v|avi|mkv)$/i.test(file.name || '');
  };

  WwhUploader.prototype._makeItem = function (f) {
    var item = {
      file: f,
      name: f.name || 'file',
      size: f.size || 0,
      loaded: 0,
      status: 'waiting',
      error: '',
      kind: this._isVideo(f) ? 'video' : 'image',
      previewUrl: ''
    };
    try {
      item.previewUrl = URL.createObjectURL(f);
    } catch (e) {
      item.previewUrl = '';
    }
    return item;
  };

  WwhUploader.prototype._revokePreview = function (item) {
    if (item && item.previewUrl) {
      try { URL.revokeObjectURL(item.previewUrl); } catch (e) { /* ignore */ }
      item.previewUrl = '';
    }
  };

  WwhUploader.prototype._revokeAllPreviews = function () {
    var self = this;
    (this.queue || []).forEach(function (it) { self._revokePreview(it); });
  };

  WwhUploader.prototype._shortName = function (name) {
    var n = String(name || 'file');
    if (n.length <= 18) return n;
    var dot = n.lastIndexOf('.');
    var ext = dot > 0 ? n.slice(dot) : '';
    var base = dot > 0 ? n.slice(0, dot) : n;
    return base.slice(0, 12) + '…' + ext;
  };

  /* Phone cameras: HEIC/HEIF/AVIF stills + MOV/M4V video — server normalizes. */
  var _ALLOWED_IMAGE_EXT = /\.(jpe?g|png|webp|heic|heif|avif)$/i;
  var _ALLOWED_VIDEO_EXT = /\.(mp4|webm|m4v|mov)$/i;
  var _DENIED_EXT = /\.(svg|svgz|html?|js|mjs|exe|bat|cmd|sh|php|py|wasm|dll|jar|apk|msi|gif)$/i;
  var _ALLOWED_IMAGE_MIME = /^image\/(jpeg|jpg|png|webp|heic|heif|avif)$/;
  var _ALLOWED_VIDEO_MIME = /^video\/(mp4|webm|quicktime|x-m4v)$/;

  WwhUploader.prototype._clientAcceptFile = function (f) {
    if (!f) return { ok: false, reason: 'empty' };
    var name = f.name || '';
    var type = (f.type || '').toLowerCase();
    if (_DENIED_EXT.test(name)) return { ok: false, reason: 'denied' };
    if (type.indexOf('image/gif') === 0 || type.indexOf('image/svg') === 0) {
      return { ok: false, reason: 'denied' };
    }
    var byExtImg = _ALLOWED_IMAGE_EXT.test(name);
    var byExtVid = _ALLOWED_VIDEO_EXT.test(name);
    var byMimeImg = type && _ALLOWED_IMAGE_MIME.test(type);
    var byMimeVid = type && _ALLOWED_VIDEO_MIME.test(type);
    /* Empty MIME is common on iOS — fall back to extension. */
    if (!type && !byExtImg && !byExtVid) return { ok: false, reason: 'type' };
    if (type && type.indexOf('image/') === 0 && !byMimeImg && !byExtImg) {
      return { ok: false, reason: 'type' };
    }
    if (type && type.indexOf('video/') === 0 && !byMimeVid && !byExtVid) {
      return { ok: false, reason: 'type' };
    }
    if (!byMimeImg && !byMimeVid && !byExtImg && !byExtVid) {
      return { ok: false, reason: 'type' };
    }
    var isVid = byMimeVid || byExtVid || (type.indexOf('video/') === 0);
    return { ok: true, kind: isVid ? 'video' : 'image' };
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
    if (this._onLbKey) document.removeEventListener('keydown', this._onLbKey);
    if (this._onListResize) window.removeEventListener('resize', this._onListResize);
    this.closePreview();
    this.cancelAll();
  };

  WwhUploader.prototype.getCaption = function () {
    return this.els.cap ? String(this.els.cap.value || '').trim() : '';
  };

  WwhUploader.prototype.isBusy = function () {
    return !!BUSY_STATES[this.state];
  };

  WwhUploader.prototype._emitState = function () {
    if (typeof this.opts.onStateChange === 'function') {
      try {
        this.opts.onStateChange(this.state, {
          queueLength: this.queue.length,
          busy: this.isBusy()
        });
      } catch (e) { /* ignore */ }
    }
  };

  WwhUploader.prototype.addFiles = function (fileList, opts) {
    opts = opts || {};
    if (this.state === 'uploading' || this.state === 'paused' || this.state === 'failed') {
      this._setStatus('اول آپلود جاری را مکث یا لغو کن.', 'err');
      return;
    }
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    var rejected = 0;
    var self = this;
    files = files.filter(function (f) {
      var v = self._clientAcceptFile(f);
      if (!v.ok) {
        rejected++;
        return false;
      }
      return true;
    });
    if (rejected && !files.length) {
      this._setStatus('فقط عکس (JPG/PNG/WebP/HEIC) یا ویدیو (MP4/MOV/WebM) مجاز است.', 'err');
      return;
    }
    if (rejected) {
      this._setStatus(this.toFa(rejected) + ' فایل نامعتبر رد شد.', 'warn');
    }
    if (typeof this.opts.filterFiles === 'function') {
      files = this.opts.filterFiles(files) || [];
    }
    if (!files.length) return;

    var newItems = files.map(function (f) { return self._makeItem(f); });
    var replace = !!opts.replace;
    if (replace || !this.queue.length) {
      this._revokeAllPreviews();
      this.queue = newItems;
      this.index = 0;
    } else {
      if (this.state === 'done' || this.state === 'cancelled') {
        var kept = [];
        this.queue.forEach(function (it) {
          if (it.status === 'waiting' || it.status === 'error' || it.status === 'paused') {
            kept.push(it);
          } else {
            self._revokePreview(it);
          }
        });
        this.queue = kept;
        this.index = 0;
      }
      this.queue = this.queue.concat(newItems);
    }
    this.state = 'queued';
    this._offlinePaused = false;
    this._renderList();
    this._updateChrome();
    this._setStatus(this.toFa(this.queue.length) + ' فایل در صف — «شروع آپلود» را بزن.', '');
    this._emitState();
    if (this.opts.autoStart) this.start();
  };

  WwhUploader.prototype.removeAt = function (i) {
    if (this.state !== 'idle' && this.state !== 'queued') return;
    if (i < 0 || i >= this.queue.length) return;
    var item = this.queue[i];
    if (!item || item.status !== 'waiting') return;
    this._revokePreview(item);
    this.queue.splice(i, 1);
    if (this.index > i) this.index--;
    if (!this.queue.length) {
      this.state = 'idle';
      this.index = 0;
      this._setStatus('', '');
    } else {
      this.state = 'queued';
      this._setStatus(this.toFa(this.queue.length) + ' فایل در صف.', '');
    }
    this._renderList();
    this._updateChrome();
    this._emitState();
  };

  WwhUploader.prototype.clearQueue = function () {
    if (this.state === 'uploading' || this.state === 'paused' || this.state === 'failed') return;
    this.gen++;
    if (this.xhr) {
      try { this.xhr.abort(); } catch (e) { /* ignore */ }
      this.xhr = null;
    }
    this.closePreview();
    this._revokeAllPreviews();
    this.queue = [];
    this.index = 0;
    this.state = 'idle';
    this._offlinePaused = false;
    this._renderList();
    this._updateChrome();
    this._setStatus('', '');
    this._emitState();
  };

  /** After success: clear done queue and invite another pick. */
  WwhUploader.prototype.addMore = function () {
    this.clearQueue();
    this._setStatus('فایل بعدی را انتخاب کن.', '');
    if (typeof this.opts.onAddMore === 'function') {
      try { this.opts.onAddMore(); } catch (e) { /* ignore */ }
    }
    try { this.els.drop.focus(); } catch (e2) { /* ignore */ }
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
    this._emitState();
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
    this._emitState();
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
    this.closePreview();
    this._revokeAllPreviews();
    this.queue = [];
    this.index = 0;
    this.state = 'idle';
    this._renderList();
    this._updateChrome();
    this._emitState();
    if (had) this._setStatus('آپلود لغو شد.', 'err');
    else this._setStatus('', '');
    if (typeof this.opts.onCancel === 'function') this.opts.onCancel();
  };

  WwhUploader.prototype.openPreview = function (i) {
    var item = this.queue[i];
    if (!item || !item.previewUrl) return;
    var body = this.els.lightboxBody;
    body.innerHTML = '';
    if (item.kind === 'video') {
      var v = document.createElement('video');
      v.src = item.previewUrl;
      v.controls = true;
      v.playsInline = true;
      v.setAttribute('playsinline', '');
      v.className = 'wwh-up__lightbox-media';
      body.appendChild(v);
      try { v.play(); } catch (e) { /* ignore */ }
    } else {
      var img = document.createElement('img');
      img.src = item.previewUrl;
      img.alt = item.name || 'پیش‌نمایش';
      img.className = 'wwh-up__lightbox-media';
      body.appendChild(img);
    }
    this.els.lightbox.hidden = false;
    document.body.classList.add('wwh-up-lb-open');
  };

  WwhUploader.prototype.closePreview = function () {
    if (!this.els || !this.els.lightbox) return;
    var vid = this.els.lightboxBody && this.els.lightboxBody.querySelector('video');
    if (vid) {
      try { vid.pause(); } catch (e) { /* ignore */ }
    }
    if (this.els.lightboxBody) this.els.lightboxBody.innerHTML = '';
    this.els.lightbox.hidden = true;
    document.body.classList.remove('wwh-up-lb-open');
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
    this._emitState();
    this._setStatus('خطا در «' + (item ? item.name : '') + '»: ' + message, 'err');
    if (typeof this.opts.onItemError === 'function') this.opts.onItemError(item, message);
  };

  WwhUploader.prototype._finishOk = function () {
    this.state = 'done';
    this.xhr = null;
    this._renderList();
    this._updateChrome();
    this._emitState();
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

  WwhUploader.prototype._setBtn = function (el, visible, disabled) {
    if (!el) return;
    el.hidden = !visible;
    el.disabled = !!disabled;
    if (disabled) el.setAttribute('aria-disabled', 'true');
    else el.removeAttribute('aria-disabled');
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
    var parts = [];
    if (this.state === 'queued' || this.state === 'idle') {
      parts.push('<strong>' + this.toFa(n) + '</strong> فایل در صف');
    } else {
      parts.push('<strong>' + this.toFa(done) + '</strong> از <strong>' + this.toFa(n) + '</strong> تمام');
    }
    if (this.state === 'uploading' && item) {
      parts.push('— فایل <strong>' + this.toFa(cur) + '</strong> از <strong>' + this.toFa(n) + '</strong>');
      parts.push('· ' + this.toFa(Math.round(((item.loaded || 0) / (item.size || 1)) * 100)) + '٪');
      parts.push('· ' + formatBytes(item.loaded) + ' / ' + formatBytes(item.size));
      parts.push('· ' + formatSpeed(this._speed));
    } else if (this.state === 'paused') {
      parts.push('— مکث‌شده');
    } else if (this.state === 'failed') {
      parts.push('— خطا؛ تلاش مجدد کن');
    } else if (this.state === 'done') {
      parts.push('— تمام شد');
    }
    this.els.summary.innerHTML = parts.join(' ');
    this.els.overall.hidden = false;
    var pct = this._overallPct();
    this.els.overallBar.style.width = pct + '%';
    this.els.overallBar.classList.toggle('is-done', this.state === 'done');
  };

  WwhUploader.prototype._updateChrome = function () {
    var has = this.queue.length > 0;
    var uploading = this.state === 'uploading';
    var paused = this.state === 'paused';
    var failed = this.state === 'failed';
    var done = this.state === 'done';
    var ready = has && (this.state === 'idle' || this.state === 'queued');
    var busy = uploading || paused || failed;

    this.els.list.hidden = !has;
    this.els.controls.hidden = !has;
    this.root.classList.toggle('is-busy', busy);
    this.root.classList.toggle('is-done', done);

    var primary = this.els.primary;
    primary.removeAttribute('aria-busy');

    if (ready) {
      primary.textContent = 'شروع آپلود';
      this._setBtn(primary, true, false);
      this._setBtn(this.els.pause, false);
      this._setBtn(this.els.clear, true, false);
      this._setBtn(this.els.cancel, false);
    } else if (uploading) {
      primary.textContent = 'در حال آپلود…';
      this._setBtn(primary, true, true);
      primary.setAttribute('aria-busy', 'true');
      this._setBtn(this.els.pause, true, false);
      this._setBtn(this.els.clear, false);
      this._setBtn(this.els.cancel, true, false);
    } else if (paused) {
      primary.textContent = 'ادامه';
      this._setBtn(primary, true, false);
      this._setBtn(this.els.pause, false);
      this._setBtn(this.els.clear, false);
      this._setBtn(this.els.cancel, true, false);
    } else if (failed) {
      primary.textContent = 'تلاش مجدد';
      this._setBtn(primary, true, false);
      this._setBtn(this.els.pause, false);
      this._setBtn(this.els.clear, false);
      this._setBtn(this.els.cancel, true, false);
    } else if (done) {
      primary.textContent = 'افزودن بیشتر';
      this._setBtn(primary, true, false);
      this._setBtn(this.els.pause, false);
      this._setBtn(this.els.clear, true, false);
      this._setBtn(this.els.cancel, false);
    } else {
      this._setBtn(primary, false);
      this._setBtn(this.els.pause, false);
      this._setBtn(this.els.clear, false);
      this._setBtn(this.els.cancel, false);
    }

    this.els.drop.style.pointerEvents = busy ? 'none' : '';
    this.els.drop.style.opacity = busy ? '0.55' : '';
    this.els.drop.setAttribute('aria-disabled', busy ? 'true' : 'false');
    this._updateSummary();
  };

  WwhUploader.prototype._renderList = function () {
    var self = this;
    this.els.list.innerHTML = this.queue.map(function (item, i) {
      return self._itemHtml(item, i);
    }).join('');
    var self2 = this;
    requestAnimationFrame(function () { self2._syncListScrollable(); });
  };

  WwhUploader.prototype._renderItem = function (i) {
    var li = this.els.list.children[i];
    var item = this.queue[i];
    if (!li || !item) {
      this._renderList();
      return;
    }
    /* Update progress/status in place so thumbnails are not recreated. */
    li.className = 'wwh-up__item is-' + item.status;
    var pct = item.size ? Math.min(100, Math.round((item.loaded / item.size) * 100)) : (item.status === 'done' ? 100 : 0);
    if (item.status === 'done') pct = 100;
    var bar = li.querySelector('.wwh-up__bar');
    if (bar) bar.style.width = pct + '%';
    var badge = li.querySelector('.wwh-up__badge');
    if (badge) {
      badge.textContent = (STATUS_LABEL[item.status] || item.status) +
        (item.status === 'uploading' || item.status === 'done' ? ' · ' + this.toFa(pct) + '٪' : '');
    }
    var meta = li.querySelector('.wwh-up__meta');
    if (meta) {
      var metaTxt = formatBytes(item.loaded) + ' / ' + formatBytes(item.size);
      if (item.status === 'uploading') metaTxt += ' · ' + formatSpeed(this._speed);
      if (item.status === 'error' && item.error) metaTxt = item.error;
      meta.textContent = metaTxt;
    }
    this._updateSummary();
  };

  WwhUploader.prototype._itemHtml = function (item, i) {
    var pct = item.size ? Math.min(100, Math.round((item.loaded / item.size) * 100)) : (item.status === 'done' ? 100 : 0);
    if (item.status === 'done') pct = 100;
    var meta = formatBytes(item.loaded) + ' / ' + formatBytes(item.size);
    if (item.status === 'uploading') meta += ' · ' + formatSpeed(this._speed);
    if (item.status === 'error' && item.error) meta = item.error;
    var canRemove = (this.state === 'idle' || this.state === 'queued') && item.status === 'waiting';
    var url = item.previewUrl || '';
    var isVid = item.kind === 'video';
    var media = !url
      ? '<div class="wwh-up__thumb wwh-up__thumb--empty" aria-hidden="true"></div>'
      : (isVid
        ? '<video class="wwh-up__thumb" src="' + escapeHtml(url) + '" muted playsinline preload="metadata" aria-hidden="true"></video>' +
          '<span class="wwh-up__play" aria-hidden="true"></span>'
        : '<img class="wwh-up__thumb" src="' + escapeHtml(url) + '" alt="" loading="lazy" decoding="async">');
    var removeBtn = canRemove
      ? '<button type="button" class="wwh-up__remove" data-remove="' + i + '" aria-label="حذف از صف">×</button>'
      : '';
    var badge =
      '<span class="wwh-up__badge">' + (STATUS_LABEL[item.status] || item.status) +
        (item.status === 'uploading' || item.status === 'done' ? ' · ' + this.toFa(pct) + '٪' : '') +
      '</span>';
    return (
      '<li class="wwh-up__item is-' + item.status + (isVid ? ' is-video' : ' is-image') + '" data-i="' + i + '">' +
        '<div class="wwh-up__card">' +
          '<button type="button" class="wwh-up__preview" data-view="' + i + '" aria-label="مشاهده ' + escapeHtml(item.name) + '">' +
            media +
            '<span class="wwh-up__card-scrim" aria-hidden="true"></span>' +
          '</button>' +
          removeBtn +
          badge +
          '<div class="wwh-up__track"><div class="wwh-up__bar" style="width:' + pct + '%"></div></div>' +
        '</div>' +
        '<div class="wwh-up__name" title="' + escapeHtml(item.name) + '">' + escapeHtml(this._shortName(item.name)) + '</div>' +
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
