// 数据驱动的侧栏显隐状态。模块不依赖 DOM 实现，Node 守卫可直接加载。
const HIDDEN_KEYS = new Set();
const VISIBILITY_LISTENERS = new Set();

export function shouldHide(response) {
  return Boolean(
    response
    && typeof response === 'object'
    && !Array.isArray(response)
    && Array.isArray(response.projects)
    && response.projects.length === 0
  );
}

export function hiddenKeys() {
  return new Set(HIDDEN_KEYS);
}

export function applyNavVisibility(navEl, keys = HIDDEN_KEYS) {
  if (!navEl?.querySelectorAll) return;
  const keySet = keys instanceof Set ? keys : new Set(keys || []);
  navEl.querySelectorAll('.nav-item').forEach(el => {
    el.hidden = keySet.has(el.dataset.key);
  });
}

export function visibleRouteEntries(routeIndex) {
  return Object.entries(routeIndex).filter(([key]) => !HIDDEN_KEYS.has(key));
}

export function onNavVisibilityChange(listener) {
  VISIBILITY_LISTENERS.add(listener);
  return () => VISIBILITY_LISTENERS.delete(listener);
}

function commitVisibility(items, decisions) {
  let changed = false;
  for (const item of items) {
    const hidden = decisions.get(item.key) === true;
    if (hidden === HIDDEN_KEYS.has(item.key)) continue;
    changed = true;
    if (hidden) HIDDEN_KEYS.add(item.key);
    else HIDDEN_KEYS.delete(item.key);
  }
  if (changed) VISIBILITY_LISTENERS.forEach(listener => listener());
}

export function createNavVisibilityController({ items, fetchVisibility, navRoot }) {
  let latestSeq = 0;

  return {
    async refresh() {
      const seq = ++latestSeq;
      const pairs = await Promise.all(items.map(async item => {
        try {
          return [item.key, Boolean(await fetchVisibility(item))];
        } catch {
          return [item.key, false];
        }
      }));

      if (seq !== latestSeq) return false;
      commitVisibility(items, new Map(pairs));
      applyNavVisibility(navRoot?.(), HIDDEN_KEYS);
      return true;
    },
  };
}

export function bindProjectChanges(target, refresh) {
  const listener = () => refresh();
  target.addEventListener('kiwi:projects-changed', listener);
  return () => target.removeEventListener('kiwi:projects-changed', listener);
}
