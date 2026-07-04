(() => {
  const STATE_KEY = '__redditBotHealerPageBridgeLoaded';
  if (window[STATE_KEY]) {
    return;
  }
  window[STATE_KEY] = true;

  const PAGE_EVENT_CHANNEL = 'reddit-bot-healer:page-event';

  function emit(type, detail) {
    window.postMessage({
      channel: PAGE_EVENT_CHANNEL,
      type,
      detail: Object.assign({ts: Date.now(), location: window.location.href}, detail || {})
    }, '*');
  }

  const originalFetch = window.fetch;
  if (typeof originalFetch === 'function') {
    window.fetch = function patchedFetch(input, init) {
      const startedAt = Date.now();
      const url = typeof input === 'string' ? input : input && input.url;
      return originalFetch.apply(this, arguments)
        .then(response => {
          emit('network_response', {
            transport: 'fetch',
            url: response.url || url || '',
            status: response.status,
            ok: response.ok,
            durationMs: Date.now() - startedAt
          });
          return response;
        })
        .catch(error => {
          emit('network_error', {
            transport: 'fetch',
            url: url || '',
            error: String(error),
            durationMs: Date.now() - startedAt
          });
          throw error;
        });
    };
  }

  const OriginalXHR = window.XMLHttpRequest;
  if (typeof OriginalXHR === 'function') {
    const originalOpen = OriginalXHR.prototype.open;
    const originalSend = OriginalXHR.prototype.send;

    OriginalXHR.prototype.open = function patchedOpen(method, url) {
      this.__redditBotHealer = {
        method,
        url,
        startedAt: 0
      };
      return originalOpen.apply(this, arguments);
    };

    OriginalXHR.prototype.send = function patchedSend() {
      const meta = this.__redditBotHealer || {};
      meta.startedAt = Date.now();
      this.addEventListener('loadend', () => {
        emit('network_response', {
          transport: 'xhr',
          method: meta.method || '',
          url: this.responseURL || meta.url || '',
          status: this.status,
          ok: this.status >= 200 && this.status < 400,
          durationMs: Date.now() - meta.startedAt
        });
      });
      return originalSend.apply(this, arguments);
    };
  }

  for (const level of ['debug', 'info', 'warn', 'error']) {
    const original = console[level];
    if (typeof original !== 'function') {
      continue;
    }
    console[level] = function patchedConsole() {
      emit('console', {
        level,
        args: Array.from(arguments).slice(0, 5).map(value => {
          if (typeof value === 'string') {
            return value.slice(0, 500);
          }
          try {
            return JSON.stringify(value).slice(0, 500);
          } catch (_error) {
            return String(value).slice(0, 500);
          }
        })
      });
      return original.apply(this, arguments);
    };
  }

  emit('page_bridge_ready', {name: 'reddit-bot-healer'});
})();
