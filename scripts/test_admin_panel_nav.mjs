#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const PANEL_JS = path.join(ROOT, 'admin-panel', 'js');
const NAV_MODULE = path.join(PANEL_JS, 'nav-visibility.mjs');

let nav;
try {
  nav = await import(`${pathToFileURL(NAV_MODULE).href}?guard=${Date.now()}`);
} catch (error) {
  if (error?.code === 'ERR_MODULE_NOT_FOUND' || String(error?.message || '').includes('nav-visibility.mjs')) {
    console.error('FAIL T-P-DOM-00 nav-visibility.mjs missing');
    process.exit(1);
  }
  console.error(`CRASH T-P-DOM-00 ${error?.stack || error}`);
  process.exit(2);
}

const failed = [];
function check(id, condition, detail = '') {
  if (condition) console.log(`PASS ${id}`);
  else {
    console.error(`FAIL ${id}${detail ? ` ${detail}` : ''}`);
    failed.push(id);
  }
}

function makeItem(key) {
  return {
    hidden: false,
    dataset: { key },
    classList: { toggle() {} },
  };
}

function makeNavRoot(items) {
  return {
    querySelectorAll(selector) {
      return selector === '.nav-item' ? items : [];
    },
    querySelector(selector) {
      const match = selector.match(/data-key=["']([^"']+)["']/);
      return match ? items.find(item => item.dataset.key === match[1]) || null : null;
    },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

class FakeEventTarget {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, listener) {
    const list = this.listeners.get(type) || [];
    list.push(listener);
    this.listeners.set(type, list);
  }
  removeEventListener(type, listener) {
    this.listeners.set(type, (this.listeners.get(type) || []).filter(item => item !== listener));
  }
  async dispatchEvent(event) {
    await Promise.all((this.listeners.get(event.type) || []).map(listener => listener(event)));
  }
}

const requiredExports = [
  'shouldHide', 'applyNavVisibility', 'hiddenKeys', 'visibleRouteEntries',
  'createNavVisibilityController', 'bindProjectChanges',
];
check(
  'T-P-DOM-00 exports present',
  requiredExports.every(name => typeof nav[name] === 'function'),
  `exports=${Object.keys(nav).sort().join(',')}`,
);

const conditionalItems = [{ key: 'projects', hideWhenEmpty: '/sync/projects' }];
const projectItem = makeItem('projects');
const dashboardItem = makeItem('dashboard');
const navRoot = makeNavRoot([dashboardItem, projectItem]);

const emptyController = nav.createNavVisibilityController({
  items: conditionalItems,
  fetchVisibility: async () => nav.shouldHide({ projects: [] }),
  navRoot: () => navRoot,
});
await emptyController.refresh();
check(
  'T-P-DOM-01 empty projects hide nav',
  projectItem.hidden === true && dashboardItem.hidden === false,
  `projects.hidden=${projectItem.hidden}`,
);

const nonEmptyController = nav.createNavVisibilityController({
  items: conditionalItems,
  fetchVisibility: async () => nav.shouldHide({ projects: [{ id: 'p1' }] }),
  navRoot: () => navRoot,
});
await nonEmptyController.refresh();
check('T-P-DOM-02 non-empty projects show nav', projectItem.hidden === false);

const errorController = nav.createNavVisibilityController({
  items: conditionalItems,
  fetchVisibility: async () => { throw new Error('network'); },
  navRoot: () => navRoot,
});
await errorController.refresh();
check('T-P-DOM-03 query failure shows nav', projectItem.hidden === false);

const malformed = [{}, { projects: null }, [], 'x', undefined, null];
check(
  'T-P-DOM-04 malformed responses show nav',
  malformed.every(value => nav.shouldHide(value) === false),
);

await emptyController.refresh();
const hidden = nav.hiddenKeys();
const routeIndex = {
  dashboard: { label: '仪表盘' },
  projects: { label: '项目分隔' },
};
const filtered = nav.visibleRouteEntries(routeIndex).map(([key]) => key);
const searchSource = await fs.readFile(path.join(PANEL_JS, 'search.js'), 'utf8');
check(
  'T-P-DOM-05 hidden page excluded from search index',
  hidden.has('projects')
    && !filtered.includes('projects')
    && searchSource.includes('visibleRouteEntries(ROUTE_INDEX)')
    && /onNavVisibilityChange\s*\([^)]*INDEX\s*=\s*null/s.test(searchSource),
  `hidden=${[...hidden]} filtered=${filtered}`,
);

await nonEmptyController.refresh();
const inputListeners = new Map();
const searchInput = {
  value: '',
  addEventListener(type, listener) { inputListeners.set(type, listener); },
  blur() {},
};
const searchDrop = {
  hidden: true,
  innerHTML: '',
  addEventListener() {},
};
const searchContainer = {
  set innerHTML(_value) {},
  querySelector(selector) {
    if (selector === '#gs-input') return searchInput;
    if (selector === '#gs-drop') return searchDrop;
    return null;
  },
  contains() { return true; },
};
globalThis.document = { addEventListener() {} };
globalThis.__KIWI_NAV_TEST__ = nav;
const runnableSearchSource = searchSource
  .replace(
    "import { CONFIG_META, CONFIG_PAGES } from './config-schema.js';",
    'const CONFIG_META = {}; const CONFIG_PAGES = {};',
  )
  .replace(
    "import { ROUTE_INDEX } from './routes.js';",
    "const ROUTE_INDEX = { dashboard: { icon: 'D', label: '仪表盘', group: '概览' }, projects: { icon: 'P', label: '项目分隔', group: '记忆机制' } };",
  )
  .replace(
    "import { onNavVisibilityChange, visibleRouteEntries } from './nav-visibility.mjs';",
    'const { onNavVisibilityChange, visibleRouteEntries } = globalThis.__KIWI_NAV_TEST__;',
  );
const searchModule = await import(
  `data:text/javascript;base64,${Buffer.from(runnableSearchSource).toString('base64')}`
);
searchModule.initSearch(searchContainer);
searchInput.value = '项目';
inputListeners.get('input')();
const wasVisible = searchDrop.innerHTML.includes('项目分隔');
await emptyController.refresh();
const vanishedWhileOpen = !searchDrop.innerHTML.includes('项目分隔');
await nonEmptyController.refresh();
const returnedWhileOpen = searchDrop.innerHTML.includes('项目分隔');
check(
  'T-P-DOM-05b open search refreshes with visibility',
  wasVisible && vanishedWhileOpen && returnedWhileOpen,
  `before=${wasVisible} hidden=${vanishedWhileOpen} shown=${returnedWhileOpen}`,
);

const routesSource = await fs.readFile(path.join(PANEL_JS, 'routes.js'), 'utf8');
const routesModule = await import(`data:text/javascript;base64,${Buffer.from(routesSource).toString('base64')}`);
check(
  'T-P-DOM-06 direct projects route remains mountable',
  Boolean(routesModule.ROUTE_INDEX?.projects)
    && routesModule.ROUTE_INDEX.projects.hideWhenEmpty === '/sync/projects',
);

const eventTarget = new FakeEventTarget();
let eventResponse = { projects: [{ id: 'p1' }] };
const eventController = nav.createNavVisibilityController({
  items: conditionalItems,
  fetchVisibility: async () => nav.shouldHide(eventResponse),
  navRoot: () => navRoot,
});
await eventController.refresh();
const unbind = nav.bindProjectChanges(eventTarget, () => eventController.refresh());
eventResponse = { projects: [] };
await eventTarget.dispatchEvent({ type: 'kiwi:projects-changed' });
const projectsSource = await fs.readFile(path.join(PANEL_JS, 'pages', 'projects.js'), 'utf8');
const appSource = await fs.readFile(path.join(PANEL_JS, 'app.js'), 'utf8');
check(
  'T-P-DOM-07 project changes trigger immediate refresh',
  projectItem.hidden === true
    && (projectsSource.match(/kiwi:projects-changed/g) || []).length >= 3
    && appSource.includes('bindProjectChanges(window, refreshNavVisibility)'),
);
unbind();

const first = deferred();
const second = deferred();
let requestNo = 0;
const raceController = nav.createNavVisibilityController({
  items: conditionalItems,
  fetchVisibility: () => (++requestNo === 1 ? first.promise : second.promise),
  navRoot: () => navRoot,
});
const older = raceController.refresh();
const newer = raceController.refresh();
second.resolve(false);
await newer;
first.resolve(true);
await older;
check(
  'T-P-DOM-08 latest response wins',
  projectItem.hidden === false && nav.hiddenKeys().has('projects') === false,
  `projects.hidden=${projectItem.hidden}`,
);

if (failed.length) {
  console.error(`FAIL: ${failed.length} admin panel nav guards failed`);
  process.exit(1);
}
console.log('PASS: 9 admin panel nav behavior guards');
