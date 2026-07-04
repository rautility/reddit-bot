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

  // Observe network resources passively. Avoid wrapping fetch/XHR because Reddit's
  // preload credential checks can otherwise point at this bridge in DevTools.
  if (typeof PerformanceObserver === 'function') {
    try {
      const networkObserver = new PerformanceObserver(list => {
        for (const entry of list.getEntries()) {
          if (!entry || !entry.name) {
            continue;
          }
          emit('network_response', {
            transport: entry.initiatorType || 'resource',
            url: entry.name,
            status: Number(entry.responseStatus || 0),
            ok: !entry.responseStatus || (
              entry.responseStatus >= 200 &&
              entry.responseStatus < 400
            ),
            durationMs: Math.round(entry.duration || 0)
          });
        }
      });
      networkObserver.observe({entryTypes: ['resource']});
    } catch (_error) {
      // Resource timing observation is diagnostic-only; control healing does not depend on it.
    }
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
