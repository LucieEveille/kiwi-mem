// Real pinned providers, fake fetch over unmodified production-capture bytes.
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
const directory = args[0];
const outputIndex = args.indexOf('--output');
const output = outputIndex >= 0 ? args[outputIndex + 1] : null;
const results = [];
const report = { ticket: 'COMPAT-02-A', scope: 'pinned provider behavior; synthetic captured streams; no real client/model', results };
const expectedIds = [];
for (const [route, kinds] of [['P', ['plain', 'memory', 'dream', 'tool', 'handoff', 'all']],
                             ['T', ['memory', 'dream', 'all']]]) {
  for (const v2 of [0, 1]) for (const kind of kinds) expectedIds.push(`${route}-v${v2}-${kind}`);
}

// TypeValidationError.message contains the rejected JSON value. Never emit it.
function safeError(error) {
  const paths = new Set();
  const seen = new Set();
  const allowed = new Set(['choices', 'error', 'delta', 'content', 'finish_reason', 'index',
    'id', 'model', 'created', 'usage', 'message', 'code', 'type', 'param']);
  function walk(value) {
    if (!value || typeof value !== 'object' || seen.has(value)) return;
    seen.add(value);
    if (Array.isArray(value.path) && value.path.length) {
      paths.add(value.path.map(p => typeof p === 'number' ? '[index]' : allowed.has(p) ? p : '[field]').join('.'));
    }
    if (Array.isArray(value)) for (const item of value) walk(item);
    else for (const key of ['cause', 'issues', 'errors']) walk(value[key]);
  }
  walk(error);
  const name = ['AI_TypeValidationError', 'AI_JSONParseError', 'AI_InvalidResponseDataError',
    'ZodError'].includes(error?.name) ? error.name : 'ProviderError';
  return { name, paths: [...paths].sort() };
}

function requireThat(condition, code) {
  if (!condition) throw Object.assign(new Error(), { probeCode: code });
}

async function run() {
  requireThat(typeof directory === 'string' && !!output, 'arguments');
  const rows = JSON.parse(fs.readFileSync(path.join(directory, 'manifest.json'), 'utf8'));
  requireThat(Array.isArray(rows) && rows.length === expectedIds.length, 'manifest-case-count');
  requireThat(new Set(rows.map(r => r.id)).size === rows.length &&
    expectedIds.every(id => rows.some(r => r.id === id)), 'manifest-identities');
  const fields = ['id', 'file', 'expect_ok', 'expect_text', 'expect_finish', 'expect_private'];
  for (const row of rows) {
    requireThat(fields.every(k => Object.hasOwn(row, k)), 'manifest-missing-field');
    requireThat(row.file === `${row.id}.sse` && row.expect_ok === true && row.expect_finish === 'stop' &&
      typeof row.expect_text === 'string' && Array.isArray(row.expect_private), 'manifest-field-shape');
    requireThat(row.expect_private.every(p => ['ev_session', 'ev_handoff', 'ev_tool', 'ev_memory', 'ev_dream'].includes(p.key)
      && Number.isInteger(p.position) && p.position >= 0), 'manifest-private-shape');
  }
  const files = fs.readdirSync(directory).filter(f => f.endsWith('.sse')).sort();
  requireThat(JSON.stringify(files) === JSON.stringify(rows.map(r => r.file).sort()), 'capture-file-identities');
  report.manifest_sha256 = createHash('sha256').update(fs.readFileSync(path.join(directory, 'manifest.json'))).digest('hex');
  report.lock_sha256 = createHash('sha256').update(fs.readFileSync(new URL('package-lock.json', import.meta.url))).digest('hex');
  for (const alias of ['oc62', 'oc72']) {
    const { createOpenAICompatible } = await import(alias);
    const version = require(`${alias}/package.json`).version;
    requireThat(version === (alias === 'oc62' ? '2.0.62' : '2.0.72'), 'sdk-version');
    for (const row of rows) {
      const bytes = fs.readFileSync(path.join(directory, row.file));
      const entry = { id: row.id, sdk: version, ok: false, errors: [], checks: {}, text: '', finish: [], metadata: [],
        capture_sha256: createHash('sha256').update(bytes).digest('hex') };
      try {
        const events = bytes.toString('utf8').split('\n\n').filter(Boolean).map(frame => {
          const raw = frame.replace(/^data: /, '').trim();
          return raw === '[DONE]' ? raw : JSON.parse(raw);
        });
        const observed = events.flatMap((e, position) => typeof e === 'object'
          ? Object.keys(e).filter(k => k.startsWith('ev_')).map(key => ({ key, position })) : []);
        entry.checks.private_occurrences = JSON.stringify(observed) === JSON.stringify(row.expect_private);
        let fetchCalls = 0;
        const provider = createOpenAICompatible({ name: 'kiwi', baseURL: 'http://kiwi.test/v1',
          fetch: async () => { fetchCalls++; return new Response(bytes, { headers: { 'content-type': 'text/event-stream' } }); } });
        const response = await provider.chatModel('m').doStream({ prompt: [{ role: 'user', content: [{ type: 'text', text: 'synthetic-input' }] }] });
        for await (const part of response.stream) {
          if (part.type === 'error') entry.errors.push(safeError(part.error));
          if (part.type === 'text-delta') entry.text += part.delta;
          if (part.type === 'finish') entry.finish.push(part.finishReason);
          if (part.type === 'response-metadata') entry.metadata.push({
            id: part.id != null, modelId: part.modelId != null, timestamp: part.timestamp != null });
        }
        Object.assign(entry.checks, {
          fetch_once: fetchCalls === 1,
          no_error_parts: entry.errors.length === 0,
          text_equal: entry.text === row.expect_text,
          finish_once: entry.finish.length === 1,
          finish_stop: entry.finish.length === 1 && entry.finish[0].unified === 'stop' && entry.finish[0].raw === 'stop',
        });
        entry.ok = Object.values(entry.checks).every(Boolean);
      } catch (error) {
        entry.errors.push(safeError(error));
      }
      results.push(entry);
      console.log(JSON.stringify({ id: entry.id, sdk: version, ok: entry.ok, errors: entry.errors,
        failed_checks: Object.entries(entry.checks).filter(([, ok]) => !ok).map(([name]) => name) }));
    }
  }
  report.counts = { PASS: results.filter(r => r.ok).length, FAIL: results.filter(r => !r.ok).length };
  report.status = report.counts.FAIL ? 'FAIL' : 'PASS';
}

try {
  await run();
} catch (error) {
  report.status = 'ERROR';
  report.error = error.probeCode || 'probe-infrastructure';
  console.log(JSON.stringify({ status: report.status, code: report.error }));
}
if (output) {
  fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
}
console.log('SUMMARY ' + JSON.stringify(report.counts || { ERROR: 1 }));
process.exitCode = report.status === 'PASS' ? 0 : 1;
