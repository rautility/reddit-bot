(() => {
  const STATE_KEY = '__redditBotHealerContentLoaded';
  if (window[STATE_KEY]) {
    return;
  }
  window[STATE_KEY] = true;

  const REQUEST_CHANNEL = 'reddit-bot-healer:request';
  const RESPONSE_CHANNEL = 'reddit-bot-healer:response';
  const PAGE_EVENT_CHANNEL = 'reddit-bot-healer:page-event';
  const HEALER_VERSION = '0.3.0';
  const EVENT_LIMIT = 500;
  const shadowRoots = new WeakSet();
  const events = [];

  const INTENTS = {
    upvote: {
      labels: ['upvote', 'up vote', 'up arrow', 'arrow up', 'vote up'],
      reject: ['downvote', 'down vote'],
      active: ['upvoted', 'text-upvote', 'bg-upvote'],
      iconHints: ['upvote', 'up-vote', 'arrow-up', 'arrow_up', 'caret-up']
    },
    downvote: {
      labels: ['downvote', 'down vote', 'down arrow', 'arrow down', 'vote down'],
      reject: ['upvote', 'up vote'],
      active: ['downvoted', 'text-downvote', 'bg-downvote'],
      iconHints: ['downvote', 'down-vote', 'arrow-down', 'arrow_down', 'caret-down']
    }
  };

  const ATTRIBUTE_NAMES = [
    'aria-label',
    'aria-pressed',
    'aria-selected',
    'aria-disabled',
    'data-testid',
    'data-state',
    'data-promoted',
    'data-action-bar-action',
    'data-click-id',
    'data-adclicklocation',
    'data-event-action',
    'data-event-detail',
    'data-vote-state',
    'slot',
    'noun',
    'name',
    'title',
    'part',
    'action',
    'icon',
    'icon-name',
    'id',
    'class',
    'disabled',
    'upvote',
    'downvote'
  ];

  const CLICKABLE_SELECTOR = [
    'button',
    '[role="button"]',
    'a',
    '[tabindex]',
    'faceplate-tracker',
    'shreddit-vote-button',
    'shreddit-post-vote-button'
  ].join(',');

  const CONTROL_SELECTOR = [
    CLICKABLE_SELECTOR,
    '[aria-label]',
    '[id]',
    '[class]',
    '[data-testid]',
    '[data-action-bar-action]',
    '[data-click-id]',
    '[data-adclicklocation]',
    '[data-event-action]',
    '[data-vote-state]',
    '[slot]',
    '[noun]',
    '[name]',
    '[part]',
    '[icon]',
    '[icon-name]',
    '[upvote]',
    '[downvote]',
    'svg',
    'use',
    'faceplate-icon'
  ].join(',');

  function now() {
    return Date.now();
  }

  function addEvent(type, detail) {
    events.push(Object.assign({type, ts: now(), url: window.location.href}, detail || {}));
    if (events.length > EVENT_LIMIT) {
      events.splice(0, events.length - EVENT_LIMIT);
    }
  }

  function recentEvents(since) {
    const cutoff = Number(since || 0);
    return events.filter(event => event.ts >= cutoff).slice(-100);
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) {
      return CSS.escape(value);
    }
    return String(value).replace(/["\\]/g, '\\$&');
  }

  function normalizeText(value) {
    return String(value || '')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
  }

  function attributeText(element) {
    if (!element || !element.getAttribute) {
      return '';
    }
    return ATTRIBUTE_NAMES
      .map(attr => element.getAttribute(attr))
      .filter(Boolean)
      .join(' ');
  }

  function compactTextContent(element) {
    const text = normalizeText(element && element.textContent);
    if (!text) {
      return '';
    }
    return text.length > 240 ? text.slice(0, 240) : text;
  }

  function descendantHintText(element) {
    if (!element || !element.querySelectorAll) {
      return '';
    }
    const values = [];
    const selector = [
      'svg',
      'use',
      'path',
      'span',
      'i',
      'faceplate-icon',
      '[class]',
      '[id]',
      '[aria-label]',
      '[icon]',
      '[icon-name]',
      '[data-testid]'
    ].join(',');
    for (const child of Array.from(element.querySelectorAll(selector)).slice(0, 30)) {
      values.push(attributeText(child));
    }
    return values.filter(Boolean).join(' ');
  }

  function ancestorHintText(element, stopAt) {
    const values = [];
    let current = element && element.parentElement;
    let depth = 0;
    while (current && current !== document.documentElement && depth < 4) {
      values.push(attributeText(current));
      if (current === stopAt || current.matches('shreddit-post,article,[data-testid="post-container"]')) {
        break;
      }
      current = current.parentElement;
      depth += 1;
    }
    return values.filter(Boolean).join(' ');
  }

  function safeText(element, clickable, options) {
    const includeAncestors = !options || options.includeAncestors !== false;
    const values = [
      attributeText(element),
      attributeText(clickable),
      descendantHintText(element),
      descendantHintText(clickable),
      compactTextContent(element)
    ];
    if (includeAncestors) {
      values.push(ancestorHintText(element, clickable));
    }
    return normalizeText(values.filter(Boolean).join(' '));
  }

  function visible(element) {
    if (!element || !element.getBoundingClientRect) {
      return false;
    }
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' &&
      style.display !== 'none' &&
      rect.width > 0 &&
      rect.height > 0;
  }

  function attributesFor(element) {
    const attrs = {};
    for (const attr of ATTRIBUTE_NAMES) {
      const value = element.getAttribute(attr);
      if (value !== null) {
        attrs[attr] = value;
      }
    }
    return attrs;
  }

  function stateFor(element, intent) {
    const attrs = attributesFor(element);
    const joined = Object.values(attrs).join(' ').toLowerCase();
    const activeHints = (INTENTS[intent] || {}).active || [];
    return {
      ariaPressed: attrs['aria-pressed'] || null,
      ariaSelected: attrs['aria-selected'] || null,
      dataState: attrs['data-state'] || null,
      disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true'),
      pressed: attrs['aria-pressed'] === 'true' ||
        attrs['aria-selected'] === 'true' ||
        attrs['data-state'] === 'on' ||
        attrs['data-state'] === 'active' ||
        activeHints.some(hint => joined.includes(hint))
    };
  }

  function boundingBoxFor(element) {
    const rect = element.getBoundingClientRect();
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      top: Math.round(rect.top),
      left: Math.round(rect.left),
      bottom: Math.round(rect.bottom),
      right: Math.round(rect.right)
    };
  }

  function isClickableElement(element) {
    return Boolean(
      element &&
      element.matches &&
      element.matches(CLICKABLE_SELECTOR)
    );
  }

  function closestClickable(element) {
    if (!element) {
      return null;
    }
    const target = element.nodeType === Node.ELEMENT_NODE ? element : element.parentElement;
    if (!target) {
      return target || null;
    }
    if (target.closest) {
      const closest = target.closest(CLICKABLE_SELECTOR);
      if (closest) {
        return closest;
      }
    }
    const root = target.getRootNode ? target.getRootNode() : null;
    if (root && root.host) {
      if (isClickableElement(root.host)) {
        return root.host;
      }
      if (root.host.closest) {
        const hostClosest = root.host.closest(CLICKABLE_SELECTOR);
        if (hostClosest) {
          return hostClosest;
        }
      }
    }
    return target;
  }

  function visibleClickTarget(element) {
    const closest = closestClickable(element);
    if (visible(closest)) {
      return closest;
    }
    if (closest && closest.querySelectorAll) {
      for (const child of closest.querySelectorAll(CLICKABLE_SELECTOR)) {
        if (visible(child)) {
          return child;
        }
      }
    }
    if (element && element.querySelectorAll) {
      for (const child of element.querySelectorAll(CLICKABLE_SELECTOR)) {
        if (visible(child)) {
          return child;
        }
      }
    }
    return visible(element) ? element : null;
  }

  function selectorFor(element) {
    const tag = element.tagName.toLowerCase();
    for (const attr of [
      'data-action-bar-action',
      'data-testid',
      'aria-label',
      'data-click-id',
      'data-adclicklocation',
      'data-event-action',
      'data-vote-state',
      'slot',
      'noun',
      'name',
      'part',
      'icon',
      'icon-name',
      'id'
    ]) {
      const value = element.getAttribute(attr);
      if (value) {
        return `${tag}[${attr}="${cssEscape(value)}"]`;
      }
    }
    return structuralSelector(element);
  }

  function structuralSelector(element) {
    const parts = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.documentElement) {
      const tag = current.tagName.toLowerCase();
      const parent = current.parentElement;
      if (!parent) {
        break;
      }
      const siblings = Array.from(parent.children).filter(child => child.tagName === current.tagName);
      const index = siblings.indexOf(current) + 1;
      parts.unshift(`${tag}:nth-of-type(${index})`);
      current = parent;
      if (parts.length >= 5) {
        break;
      }
    }
    return parts.length ? parts.join(' > ') : null;
  }

  function candidateId(selector, text, rect) {
    const raw = `${selector || ''}|${text || ''}|${rect.x},${rect.y},${rect.width},${rect.height}`;
    let hash = 0;
    for (let index = 0; index < raw.length; index += 1) {
      hash = ((hash << 5) - hash + raw.charCodeAt(index)) | 0;
    }
    return `control-${Math.abs(hash)}`;
  }

  function normalizeUrl(value) {
    try {
      const url = new URL(value, window.location.href);
      return `${url.hostname}${url.pathname}`.replace(/\/+$/, '').toLowerCase();
    } catch (_error) {
      return String(value || '').replace(/\/+$/, '').toLowerCase();
    }
  }

  function elementMatchesPostUrl(element, postUrl) {
    if (!postUrl) {
      return false;
    }
    const wanted = normalizeUrl(postUrl);
    const values = [
      element.getAttribute('permalink'),
      element.getAttribute('content-href'),
      element.getAttribute('href')
    ].filter(Boolean);
    for (const anchor of element.querySelectorAll ? element.querySelectorAll('a[href]') : []) {
      values.push(anchor.href);
    }
    return values.some(value => {
      const normalized = normalizeUrl(value);
      return normalized.includes(wanted) || wanted.includes(normalized);
    });
  }

  function postScope(postUrl) {
    if (!postUrl) {
      return document;
    }
    const selectors = [
      'shreddit-post',
      'article',
      '[data-testid="post-container"]',
      '[slot="post"]',
      '[permalink]',
      '[content-href]'
    ];
    for (const element of document.querySelectorAll(selectors.join(','))) {
      if (elementMatchesPostUrl(element, postUrl)) {
        return element;
      }
    }
    return document;
  }

  function collectRoots(root, output) {
    if (!root || !root.querySelectorAll) {
      return;
    }
    output.push(root);
    if (root.shadowRoot) {
      collectRoots(root.shadowRoot, output);
    }
    for (const element of root.querySelectorAll('*')) {
      if (element.shadowRoot) {
        collectRoots(element.shadowRoot, output);
      }
    }
  }

  function elementWithinScope(element, scope) {
    if (scope === document) {
      return true;
    }
    if (scope.contains(element)) {
      return true;
    }
    let root = element.getRootNode ? element.getRootNode() : null;
    while (root && root.host) {
      if (root.host === scope || scope.contains(root.host)) {
        return true;
      }
      root = root.host.getRootNode ? root.host.getRootNode() : null;
    }
    return false;
  }

  function labelMatchScore(text, labels, evidence, prefix, exactScore, containsScore) {
    let score = 0;
    for (const label of labels) {
      if (text === label) {
        score = Math.max(score, exactScore);
        evidence.push(`${prefix} exact label match: ${label}`);
      } else if (text.includes(label)) {
        score = Math.max(score, containsScore);
        evidence.push(`${prefix} contains label: ${label}`);
      }
    }
    return score;
  }

  function targetsForEvidence(element, clickable) {
    const targets = [];
    const seen = new WeakSet();
    for (const target of [element, clickable]) {
      if (target && !seen.has(target)) {
        targets.push(target);
        seen.add(target);
      }
    }
    let current = element && element.parentElement;
    let depth = 0;
    while (current && current !== document.documentElement && depth < 3) {
      if (!seen.has(current)) {
        targets.push(current);
        seen.add(current);
      }
      if (current.matches('shreddit-post,article,[data-testid="post-container"]')) {
        break;
      }
      current = current.parentElement;
      depth += 1;
    }
    return targets;
  }

  function intentAttributeScore(element, clickable, intent, evidence) {
    const config = INTENTS[intent] || {labels: [intent], iconHints: []};
    let bestScore = 0;
    for (const target of targetsForEvidence(element, clickable)) {
      for (const attr of ATTRIBUTE_NAMES) {
        if (!target.hasAttribute || !target.hasAttribute(attr)) {
          continue;
        }
        const value = normalizeText(target.getAttribute(attr));
        const attrLabel = `${target.tagName.toLowerCase()}[${attr}]`;
        if (attr === intent) {
          bestScore = Math.max(bestScore, 86);
          evidence.push(`intent attribute present: ${attrLabel}`);
        }
        if (!value) {
          continue;
        }
        if (value === intent || config.labels.includes(value)) {
          bestScore = Math.max(bestScore, 84);
          evidence.push(`exact intent attribute value: ${attrLabel}=${value}`);
        } else if (value.includes(intent) || config.labels.some(label => value.includes(label))) {
          bestScore = Math.max(bestScore, 62);
          evidence.push(`intent attribute value contains ${intent}: ${attrLabel}`);
        } else if (config.iconHints.some(hint => value.includes(hint))) {
          bestScore = Math.max(bestScore, 58);
          evidence.push(`icon hint attribute value: ${attrLabel}`);
        }
      }
    }
    return bestScore;
  }

  function hasSpecificIntentAttribute(element, intent) {
    const config = INTENTS[intent] || {labels: [intent], iconHints: []};
    for (const attr of ATTRIBUTE_NAMES) {
      if (!element.hasAttribute || !element.hasAttribute(attr)) {
        continue;
      }
      if (attr === intent) {
        return true;
      }
      const value = normalizeText(element.getAttribute(attr));
      if (
        value === intent ||
        config.labels.includes(value) ||
        value.includes(intent) ||
        config.labels.some(label => value.includes(label)) ||
        config.iconHints.some(hint => value.includes(hint))
      ) {
        return true;
      }
    }
    return false;
  }

  function controlCenter(element) {
    const rect = boundingBoxFor(element);
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    };
  }

  function uniqueVisibleControls(root) {
    if (!root || !root.querySelectorAll) {
      return [];
    }
    const controls = [];
    const seen = new WeakSet();
    for (const element of root.querySelectorAll(CLICKABLE_SELECTOR)) {
      const target = visibleClickTarget(element);
      if (!target || seen.has(target)) {
        continue;
      }
      seen.add(target);
      controls.push(target);
    }
    return controls;
  }

  function nearestControlCluster(clickable, scope) {
    let current = clickable && clickable.parentElement;
    let depth = 0;
    while (current && current !== document.documentElement && depth < 5) {
      if (scope !== document && !elementWithinScope(current, scope)) {
        current = current.parentElement;
        depth += 1;
        continue;
      }
      const controls = uniqueVisibleControls(current);
      if (controls.length >= 2 && controls.length <= 8 && controls.includes(clickable)) {
        return {container: current, controls};
      }
      current = current.parentElement;
      depth += 1;
    }
    return null;
  }

  function votePairScore(clickable, intent, scope, directText, evidence) {
    if (!clickable || directText.includes(intent)) {
      return 0;
    }
    const config = INTENTS[intent] || {reject: []};
    const cluster = nearestControlCluster(clickable, scope);
    if (!cluster) {
      return 0;
    }
    const controls = cluster.controls;
    const ownIndex = controls.indexOf(clickable);
    if (ownIndex < 0) {
      return 0;
    }
    const opposite = controls.find(control => {
      if (control === clickable) {
        return false;
      }
      const text = safeText(control, control, {includeAncestors: false});
      return config.reject.some(label => text.includes(label));
    });
    if (!opposite) {
      return 0;
    }
    const ownCenter = controlCenter(clickable);
    const oppositeCenter = controlCenter(opposite);
    const beforeOpposite = ownIndex < controls.indexOf(opposite);
    const aboveOpposite = ownCenter.y + 2 < oppositeCenter.y;
    const leftOfOpposite = ownCenter.x + 2 < oppositeCenter.x;
    const afterOpposite = ownIndex > controls.indexOf(opposite);
    const belowOpposite = ownCenter.y > oppositeCenter.y + 2;
    const rightOfOpposite = ownCenter.x > oppositeCenter.x + 2;
    if (
      (intent === 'upvote' && (beforeOpposite || aboveOpposite || leftOfOpposite)) ||
      (intent === 'downvote' && (afterOpposite || belowOpposite || rightOfOpposite))
    ) {
      evidence.push('inferred from adjacent vote pair');
      return 44;
    }
    return 0;
  }

  function scopeProximityScore(clickable, scope, evidence) {
    if (scope === document || !clickable || !scope.getBoundingClientRect) {
      return 0;
    }
    const rect = boundingBoxFor(clickable);
    const scopeRect = boundingBoxFor(scope);
    const verticallyNearPost =
      rect.bottom >= scopeRect.top - 32 &&
      rect.top <= scopeRect.bottom + 32;
    const horizontallyNearPost =
      rect.right >= scopeRect.left - 96 &&
      rect.left <= scopeRect.right + 96;
    if (verticallyNearPost && horizontallyNearPost) {
      evidence.push('near requested post bounds');
      return 8;
    }
    return 0;
  }

  function scoreElement(element, intent, scope, scopeName) {
    const clickable = visibleClickTarget(element);
    if (!clickable) {
      return null;
    }
    if (!isClickableElement(clickable)) {
      return null;
    }
    const config = INTENTS[intent] || {labels: [intent], reject: []};
    const directText = safeText(element, clickable, {includeAncestors: false});
    const text = safeText(element, clickable, {includeAncestors: true});
    const directPositive = config.labels.some(label => directText.includes(label));
    const directReject = config.reject.some(label => directText.includes(label));
    const specificIntentAttribute = hasSpecificIntentAttribute(clickable, intent);
    const evidence = [];
    let score = 0;

    if (directReject && !directPositive) {
      return null;
    }
    if (directPositive && directReject && !specificIntentAttribute) {
      return null;
    }

    score += labelMatchScore(directText, config.labels, evidence, 'direct', 92, 68);
    if (score === 0) {
      score += labelMatchScore(text, config.labels, evidence, 'combined', 48, 48);
    }
    score += intentAttributeScore(element, clickable, intent, evidence);
    score += votePairScore(clickable, intent, scope, directText, evidence);

    if (score === 0) {
      return null;
    }

    if (config.reject.some(label => text.includes(label)) && !directPositive && score < 80) {
      score -= 28;
      evidence.push('conflicting vote label nearby');
    }

    const tag = clickable.tagName.toLowerCase();
    if (tag === 'button') {
      score += 16;
      evidence.push('clickable button');
    }
    if (clickable.getAttribute('role') === 'button') {
      score += 10;
      evidence.push('role button');
    }
    if (clickable.hasAttribute('aria-pressed')) {
      score += 8;
      evidence.push('has aria-pressed');
    }
    if (scope !== document && elementWithinScope(clickable, scope)) {
      score += 10;
      evidence.push('inside requested post scope');
    }
    score += scopeProximityScore(clickable, scope, evidence);

    const controlState = stateFor(clickable, intent);
    if (controlState.disabled) {
      score -= 35;
      evidence.push('disabled');
    }
    const actionable = !controlState.disabled;
    if (!actionable) {
      score = Math.min(score, 100);
    }

    const rect = boundingBoxFor(clickable);
    const selector = selectorFor(clickable);
    return {
      id: candidateId(selector, text, rect),
      intent,
      selector,
      confidence: Math.max(0, Math.min(1, score / 145)),
      actionable,
      text: text.slice(0, 180),
      directText: directText.slice(0, 180),
      attributes: attributesFor(clickable),
      boundingBox: rect,
      state: controlState,
      scope: scopeName,
      evidence,
      _score: score,
      _element: clickable
    };
  }

  function publicCandidate(candidate) {
    const copy = Object.assign({}, candidate);
    delete copy._element;
    delete copy._score;
    return copy;
  }

  function candidateMeetsActionableThreshold(candidate, minConfidence) {
    return Boolean(
      candidate &&
      candidate.actionable &&
      candidate.confidence >= minConfidence
    );
  }

  function buildScanResult(payload, passIndex, scopes, candidates, nearMisses, completedScopes) {
    candidates.sort((left, right) => right.confidence - left.confidence);
    nearMisses.sort((left, right) => right.confidence - left.confidence);
    const publicCandidates = candidates.slice(0, 20).map(publicCandidate);
    const publicNearMisses = nearMisses.slice(0, 20).map(publicCandidate);
    const bestCandidate = publicCandidates[0] || null;
    const minConfidence = Number(payload.minConfidence || 0);
    const meetsMinConfidence = candidateMeetsActionableThreshold(bestCandidate, minConfidence);
    if (bestCandidate) {
      addEvent('found_control', {
        intent: String(payload.intent || '').toLowerCase(),
        candidateId: bestCandidate.id,
        selector: bestCandidate.selector,
        confidence: bestCandidate.confidence,
        actionable: bestCandidate.actionable,
        state: bestCandidate.state,
        scanPass: passIndex + 1,
        meetsMinConfidence
      });
    } else {
      addEvent('control_scan_empty', {
        intent: String(payload.intent || '').toLowerCase(),
        scanPass: passIndex + 1,
        nearMisses: publicNearMisses.length
      });
    }
    return {
      ok: true,
      intent: String(payload.intent || '').toLowerCase(),
      url: window.location.href,
      minConfidence,
      meetsMinConfidence,
      scanPass: passIndex + 1,
      scopesSearched: (completedScopes || scopes).map(scopeInfo => scopeInfo.name),
      bestCandidate,
      candidates: publicCandidates,
      nearMisses: publicNearMisses,
      events: recentEvents(payload.since)
    };
  }

  function scopeList(postUrl) {
    const primary = postScope(postUrl);
    const scopes = [];
    const seen = new WeakSet();
    function add(scope, name) {
      if (!scope || seen.has(scope)) {
        return;
      }
      seen.add(scope);
      scopes.push({scope, name});
    }
    add(primary, primary === document ? 'document' : 'post');
    if (primary !== document) {
      let parent = primary.parentElement;
      let depth = 0;
      while (parent && parent !== document.documentElement && depth < 2) {
        add(parent, `post-parent-${depth + 1}`);
        parent = parent.parentElement;
        depth += 1;
      }
      add(document, 'document-fallback');
    }
    return scopes;
  }

  function looksVoteRelated(text) {
    return /\b(upvote|downvote|vote|karma|score)\b/.test(text) ||
      text.includes('arrow-up') ||
      text.includes('arrow_down') ||
      text.includes('arrow-down') ||
      text.includes('arrow_up') ||
      text.includes('caret-up') ||
      text.includes('caret-down') ||
      text.includes('icon-up') ||
      text.includes('icon-down');
  }

  function nearMissForElement(element, intent, scopeName) {
    const clickable = visibleClickTarget(element);
    if (!clickable) {
      return null;
    }
    const text = safeText(element, clickable, {includeAncestors: true});
    if (!looksVoteRelated(text)) {
      return null;
    }
    const rect = boundingBoxFor(clickable);
    const selector = selectorFor(clickable);
    return {
      id: candidateId(selector, text, rect),
      intent,
      selector,
      confidence: 0,
      text: text.slice(0, 180),
      directText: safeText(element, clickable, {includeAncestors: false}).slice(0, 180),
      attributes: attributesFor(clickable),
      boundingBox: rect,
      state: stateFor(clickable, intent),
      scope: scopeName,
      evidence: ['visible vote-related control but insufficient intent evidence'],
      _element: clickable
    };
  }

  function scanControl(payload, passIndex) {
    const intent = String(payload.intent || '').toLowerCase();
    const minConfidence = Number(payload.minConfidence || 0);
    const scopes = scopeList(payload.postUrl);
    const candidateByElement = new WeakMap();
    const candidateElements = [];
    const nearSeen = new WeakSet();
    const nearMisses = [];
    const completedScopes = [];

    for (const scopeInfo of scopes) {
      const roots = [];
      collectRoots(scopeInfo.scope, roots);
      for (const root of roots) {
        for (const element of root.querySelectorAll(CONTROL_SELECTOR)) {
          const clickable = visibleClickTarget(element);
          if (!clickable) {
            continue;
          }
          const candidate = scoreElement(element, intent, scopeInfo.scope, scopeInfo.name);
          if (candidate) {
            const existing = candidateByElement.get(candidate._element);
            if (!existing) {
              candidateElements.push(candidate._element);
              candidateByElement.set(candidate._element, candidate);
            } else if (candidate.confidence > existing.confidence) {
              candidateByElement.set(candidate._element, candidate);
            }
            if (
              scopeInfo.name !== 'document-fallback' &&
              candidateMeetsActionableThreshold(candidate, minConfidence)
            ) {
              const candidates = [candidate];
              const filteredNearMisses = nearMisses.filter(
                nearMiss => !candidateByElement.has(nearMiss._element)
              );
              return buildScanResult(
                payload,
                passIndex,
                scopes,
                candidates,
                filteredNearMisses,
                completedScopes.concat([scopeInfo])
              );
            }
            continue;
          }
          if (!nearSeen.has(clickable) && nearMisses.length < 30) {
            const nearMiss = nearMissForElement(element, intent, scopeInfo.name);
            if (nearMiss) {
              nearSeen.add(clickable);
              nearMisses.push(nearMiss);
            }
          }
        }
      }
      completedScopes.push(scopeInfo);
    }

    const candidates = [];
    const filteredNearMisses = nearMisses.filter(nearMiss => !candidateByElement.has(nearMiss._element));
    for (const element of candidateElements) {
      const candidate = candidateByElement.get(element);
      if (candidate.confidence >= 0.24) {
        candidates.push(candidate);
      } else {
        filteredNearMisses.push(candidate);
      }
    }

    return buildScanResult(payload, passIndex, scopes, candidates, filteredNearMisses, completedScopes);
  }

  function sleep(ms) {
    return new Promise(resolve => window.setTimeout(resolve, ms));
  }

  function betterScanResult(current, next) {
    if (!current) {
      return next;
    }
    const currentConfidence = current.bestCandidate ? current.bestCandidate.confidence : -1;
    const nextConfidence = next.bestCandidate ? next.bestCandidate.confidence : -1;
    if (next.meetsMinConfidence && !current.meetsMinConfidence) {
      return next;
    }
    if (nextConfidence > currentConfidence) {
      return next;
    }
    if (nextConfidence === currentConfidence && next.nearMisses.length > current.nearMisses.length) {
      return next;
    }
    return current;
  }

  async function findControl(payload) {
    const minConfidence = Number(payload.minConfidence || 0);
    const scanPasses = Math.max(1, Math.min(5, Number(payload.scanPasses || payload.retries || 3)));
    const settleMs = Math.max(0, Math.min(750, Number(payload.settleMs || 200)));
    let bestResult = null;
    for (let passIndex = 0; passIndex < scanPasses; passIndex += 1) {
      const result = scanControl(payload, passIndex);
      result.scanPasses = scanPasses;
      result.settleMs = settleMs;
      bestResult = betterScanResult(bestResult, result);
      if (candidateMeetsActionableThreshold(result.bestCandidate, minConfidence)) {
        return result;
      }
      if (passIndex < scanPasses - 1) {
        await sleep(settleMs);
      }
    }
    if (bestResult) {
      bestResult.scanPasses = scanPasses;
      bestResult.settleMs = settleMs;
    }
    return bestResult || scanControl(payload, 0);
  }

  function postUrlFromElement(element) {
    const values = [
      element && element.getAttribute && element.getAttribute('permalink'),
      element && element.getAttribute && element.getAttribute('content-href'),
      element && element.getAttribute && element.getAttribute('href')
    ].filter(Boolean);
    for (const anchor of element && element.querySelectorAll ? element.querySelectorAll('a[href*="/comments/"]') : []) {
      values.push(anchor.href || anchor.getAttribute('href'));
    }
    for (const value of values) {
      try {
        const url = new URL(value, window.location.href);
        if (url.pathname.includes('/comments/')) {
          return url.href;
        }
      } catch (_error) {
        // Ignore malformed candidate hrefs.
      }
    }
    return '';
  }

  function pageShape() {
    let shadowHostCount = 0;
    for (const element of document.querySelectorAll('*')) {
      if (element.shadowRoot) {
        shadowHostCount += 1;
      }
    }
    const shredditPosts = document.querySelectorAll('shreddit-post').length;
    const searchTrackers = document.querySelectorAll('search-telemetry-tracker').length;
    const bodyText = normalizeText(document.body && document.body.textContent).slice(0, 2000);
    return {
      shredditPosts,
      articles: document.querySelectorAll('article').length,
      postContainers: document.querySelectorAll('[data-testid="post-container"]').length,
      commentLinks: document.querySelectorAll('a[href*="/comments/"]').length,
      searchTrackers,
      shadowHostCount,
      appShells: document.querySelectorAll('shreddit-app, faceplate-batch, faceplate-tracker').length,
      wrapperMode: searchTrackers > 0 && shredditPosts === 0 ? 'search-telemetry-tracker' : 'standard',
      recaptchaResources: document.querySelectorAll('iframe[src*="recaptcha"], script[src*="recaptcha"]').length,
      challengeText: /\b(captcha|blocked|unusual traffic|try again later)\b/.test(bodyText)
    };
  }

  function nearestSearchCard(element) {
    let current = element;
    let depth = 0;
    while (current && current !== document.documentElement && depth < 8) {
      if (
        current.matches &&
        current.matches('shreddit-post, article, [data-testid="post-container"], search-telemetry-tracker, faceplate-tracker')
      ) {
        return current;
      }
      current = current.parentElement || (current.getRootNode && current.getRootNode().host) || null;
      depth += 1;
    }
    return element;
  }

  function searchResultState(card, anchor) {
    const joined = normalizeText([
      compactTextContent(card),
      attributeText(card),
      attributeText(anchor),
      descendantHintText(card)
    ].filter(Boolean).join(' '));
    const promoted = /\b(promoted|sponsored|advertisement|advertise|ad)\b/.test(joined) ||
      card.hasAttribute && (
        card.hasAttribute('promoted') ||
        card.hasAttribute('data-promoted') ||
        card.getAttribute('data-adclicklocation')
      );
    const archived = /\b(archived|this post is archived)\b/.test(joined) ||
      card.querySelector && Boolean(card.querySelector('[aria-label*="archived" i], [title*="archived" i]'));
    const deleted = /\b(deleted by user|\[deleted\]|deleted post)\b/.test(joined);
    const removed = /\b(removed by moderators|removed post|\[removed\])\b/.test(joined);
    return {
      promoted: Boolean(promoted),
      archived: Boolean(archived),
      deleted: Boolean(deleted),
      removed: Boolean(removed),
      hidden: !visible(card) || !visible(anchor)
    };
  }

  function titleForSearchResult(card, anchor) {
    const titleSelectors = [
      '[slot="title"]',
      '[data-testid="post-title"]',
      'h1',
      'h2',
      'h3',
      'a[href*="/comments/"]'
    ];
    for (const selector of titleSelectors) {
      const element = card.querySelector && card.querySelector(selector);
      const title = compactTextContent(element);
      if (title) {
        return title.slice(0, 180);
      }
    }
    return compactTextContent(anchor).slice(0, 180);
  }

  function subredditForSearchResult(card) {
    const text = compactTextContent(card);
    const match = text.match(/r\/[A-Za-z0-9_]+/);
    return match ? match[0] : '';
  }

  function authorForSearchResult(card) {
    const text = compactTextContent(card);
    const match = text.match(/u\/[A-Za-z0-9_-]+/);
    return match ? match[0] : '';
  }

  function searchResultId(url, rect) {
    return candidateId(url, '', rect);
  }

  function scoreSearchResult(card, anchor, query) {
    if (!visible(card) || !visible(anchor)) {
      return null;
    }
    const url = postUrlFromElement(card) || postUrlFromElement(anchor);
    if (!url) {
      return null;
    }
    const state = searchResultState(card, anchor);
    const evidence = [];
    let score = 72;
    const title = titleForSearchResult(card, anchor);
    const queryTerms = normalizeText(query).split(' ').filter(term => term.length > 2);
    const haystack = normalizeText(`${title} ${compactTextContent(card)}`);
    const matchedTerms = queryTerms.filter(term => haystack.includes(term));
    if (matchedTerms.length) {
      score += Math.min(18, matchedTerms.length * 6);
      evidence.push(`matched query terms: ${matchedTerms.join(', ')}`);
    }
    if (card.matches && card.matches('shreddit-post')) {
      score += 12;
      evidence.push('shreddit-post card');
    } else if (card.matches && card.matches('article')) {
      score += 8;
      evidence.push('article card');
    }
    if (anchor.matches && anchor.matches('a[href*="/comments/"]')) {
      score += 10;
      evidence.push('comments permalink');
    }
    if (state.promoted) {
      score -= 80;
      evidence.push('rejected promoted result');
    }
    if (state.archived) {
      score -= 80;
      evidence.push('rejected archived result');
    }
    if (state.deleted) {
      score -= 80;
      evidence.push('rejected deleted result');
    }
    if (state.removed) {
      score -= 80;
      evidence.push('rejected removed result');
    }
    if (state.hidden) {
      score -= 60;
      evidence.push('hidden result');
    }
    const actionable = !state.promoted && !state.archived && !state.deleted && !state.removed && !state.hidden;
    const rect = boundingBoxFor(anchor);
    return {
      id: searchResultId(url, rect),
      selector: selectorFor(anchor),
      url,
      title,
      subreddit: subredditForSearchResult(card),
      author: authorForSearchResult(card),
      confidence: Math.max(0, Math.min(1, score / 120)),
      actionable,
      text: compactTextContent(card).slice(0, 240),
      attributes: attributesFor(anchor),
      boundingBox: rect,
      state,
      evidence,
      _score: score,
      _element: anchor
    };
  }

  function findSearchResult(payload) {
    const query = String(payload.query || '');
    const minConfidence = Number(payload.minConfidence || 0);
    const maxResults = Math.max(5, Math.min(80, Number(payload.maxResults || 30)));
    const seenUrls = new Set();
    const candidates = [];
    const rejected = [];
    const anchors = Array.from(document.querySelectorAll('a[href*="/comments/"]')).slice(0, maxResults * 3);
    for (const anchor of anchors) {
      const card = nearestSearchCard(anchor);
      const candidate = scoreSearchResult(card, anchor, query);
      if (!candidate || seenUrls.has(candidate.url)) {
        continue;
      }
      seenUrls.add(candidate.url);
      if (candidate.actionable && candidate.confidence >= 0.2) {
        candidates.push(candidate);
      } else {
        rejected.push(candidate);
      }
      if (candidates.length >= maxResults) {
        break;
      }
    }
    candidates.sort((left, right) => right.confidence - left.confidence);
    rejected.sort((left, right) => right.confidence - left.confidence);
    const publicCandidates = candidates.slice(0, maxResults).map(publicCandidate);
    const publicRejected = rejected.slice(0, 20).map(publicCandidate);
    const bestCandidate = publicCandidates[0] || null;
    const meetsMinConfidence = candidateMeetsActionableThreshold(bestCandidate, minConfidence);
    addEvent(bestCandidate ? 'found_search_result' : 'search_result_scan_empty', {
      query,
      candidateId: bestCandidate && bestCandidate.id,
      confidence: bestCandidate && bestCandidate.confidence,
      meetsMinConfidence,
      pageShape: pageShape()
    });
    return {
      ok: true,
      query,
      url: window.location.href,
      minConfidence,
      meetsMinConfidence,
      bestCandidate,
      candidates: publicCandidates,
      rejected: publicRejected,
      pageShape: pageShape(),
      events: recentEvents(payload.since)
    };
  }

  function deepQuery(selector, scope) {
    const roots = [];
    collectRoots(scope || document, roots);
    for (const root of roots) {
      try {
        const element = root.querySelector(selector);
        if (element && visible(element)) {
          return element;
        }
      } catch (_error) {
        return null;
      }
    }
    return null;
  }

  async function confirmControlState(payload) {
    const intent = String(payload.intent || '').toLowerCase();
    const scope = postScope(payload.postUrl);
    let element = payload.selector ? deepQuery(payload.selector, scope) : null;
    if (!element) {
      const result = await findControl(payload);
      const best = result.bestCandidate;
      element = best && best.selector ? deepQuery(best.selector, scope) : null;
    }
    if (!element) {
      return {ok: false, intent, confirmed: false, error: 'Control no longer found'};
    }
    const state = stateFor(element, intent);
    const expectedPressed = payload.expectedPressed !== false;
    const confirmed = Boolean(state.pressed) === expectedPressed;
    addEvent('confirmed_control_state', {
      intent,
      selector: payload.selector || selectorFor(element),
      confirmed,
      state
    });
    return {
      ok: true,
      intent,
      confirmed,
      state,
      attributes: attributesFor(element),
      boundingBox: boundingBoxFor(element),
      events: recentEvents(payload.since)
    };
  }

  async function handleRequest(message) {
    const payload = message.payload || {};
    if (message.command === 'ping') {
      return {
        ok: true,
        name: 'reddit-bot-healer',
        version: HEALER_VERSION,
        url: window.location.href
      };
    }
    if (message.command === 'find_control') {
      return findControl(payload);
    }
    if (message.command === 'find_search_result') {
      return findSearchResult(payload);
    }
    if (message.command === 'confirm_control_state') {
      return confirmControlState(payload);
    }
    if (message.command === 'snapshot_events') {
      return {ok: true, events: recentEvents(payload.since)};
    }
    return {ok: false, error: `Unknown healer command: ${message.command || ''}`};
  }

  window.addEventListener('message', event => {
    if (event.source !== window) {
      return;
    }
    const message = event.data || {};
    if (message.channel === PAGE_EVENT_CHANNEL) {
      addEvent(message.type || 'page_event', message.detail || {});
      return;
    }
    if (message.channel !== REQUEST_CHANNEL) {
      return;
    }
    Promise.resolve(handleRequest(message))
      .then(response => {
        window.postMessage({
          channel: RESPONSE_CHANNEL,
          requestId: message.requestId,
          response
        }, '*');
      })
      .catch(error => {
        window.postMessage({
          channel: RESPONSE_CHANNEL,
          requestId: message.requestId,
          response: {ok: false, error: String(error && error.message ? error.message : error)}
        }, '*');
      });
  });

  document.addEventListener('click', event => {
    const clickable = visibleClickTarget(event.target) || closestClickable(event.target);
    if (!clickable) {
      return;
    }
    addEvent('click', {
      selector: selectorFor(clickable),
      text: safeText(clickable, clickable).slice(0, 120),
      attributes: attributesFor(clickable),
      boundingBox: boundingBoxFor(clickable)
    });
  }, true);

  function observeRoot(root) {
    if (!root || shadowRoots.has(root)) {
      return;
    }
    shadowRoots.add(root);
    const observer = new MutationObserver(mutations => {
      for (const mutation of mutations) {
        if (mutation.type === 'attributes') {
          const target = mutation.target;
          if (target && target.matches && target.matches(CONTROL_SELECTOR)) {
            addEvent('dom_attribute_changed', {
              attributeName: mutation.attributeName,
              selector: selectorFor(target),
              text: safeText(target, visibleClickTarget(target) || target).slice(0, 120),
              attributes: attributesFor(target)
            });
          }
        } else if (mutation.addedNodes && mutation.addedNodes.length) {
          addEvent('dom_mutation', {addedNodes: mutation.addedNodes.length});
        }
      }
      scanShadowRoots();
    });
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        'aria-pressed',
        'aria-selected',
        'aria-label',
        'aria-disabled',
        'data-state',
        'data-promoted',
        'data-action-bar-action',
        'data-click-id',
        'data-adclicklocation',
        'data-event-action',
        'data-vote-state',
        'slot',
        'noun',
        'name',
        'part',
        'icon',
        'icon-name',
        'class',
        'disabled',
        'upvote',
        'downvote'
      ]
    });
  }

  function scanShadowRoots() {
    observeRoot(document);
    for (const element of document.querySelectorAll('*')) {
      if (element.shadowRoot) {
        observeRoot(element.shadowRoot);
      }
    }
  }

  function injectPageBridge() {
    const script = document.createElement('script');
    script.src = chrome.runtime.getURL('page_bridge.js');
    script.async = false;
    script.onload = () => script.remove();
    (document.documentElement || document.head || document.body).appendChild(script);
  }

  scanShadowRoots();
  window.setInterval(scanShadowRoots, 1000);
  injectPageBridge();
  addEvent('bridge_ready', {name: 'reddit-bot-healer', version: HEALER_VERSION});
})();
