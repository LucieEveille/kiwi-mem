// ============================================================
// api.js — 网络层 + 纯工具（无 DOM 依赖）
// 统一处理 kiwi-mem 的两种错误约定：
//   1) 多数 /admin、/debug、/comments：HTTP 200 + {error:"..."}
//   2) /reminders、/sync、/admin/search-*：真实 HTTP 状态码
// jfetch 在「响应含真值 error 键 或 HTTP>=400」时 throw。
// ============================================================

export const API = window.location.origin;

export async function request(path, { method = 'GET', body, headers, signal } = {}) {
  const opts = { method, headers: { ...(headers || {}) }, signal };
  if (body !== undefined && body !== null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = typeof body === 'string' ? body : JSON.stringify(body);
  }
  return fetch(API + path, opts);
}

export async function jfetch(path, opts = {}) {
  let res;
  try {
    res = await request(path, opts);
  } catch (e) {
    throw new Error('网络错误：无法连接后端');
  }
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch {
    if (!res.ok) throw new Error(`服务器错误 (${res.status})`);
    return text; // non-JSON body (rare)
  }
  if (!res.ok) throw new Error(data?.error || `服务器错误 (${res.status})`);
  if (data && typeof data === 'object' && !Array.isArray(data) && data.error) {
    throw new Error(data.error);
  }
  return data;
}

export const get  = (p)    => jfetch(p);
export const post = (p, b) => jfetch(p, { method: 'POST',   body: b ?? {} });
export const put  = (p, b) => jfetch(p, { method: 'PUT',    body: b ?? {} });
export const del  = (p, b) => jfetch(p, { method: 'DELETE', ...(b !== undefined ? { body: b } : {}) });

// 触发浏览器下载（GET）
export function download(path) {
  const a = document.createElement('a');
  a.href = API + path;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// SSE：POST 一个流式端点，逐事件回调。返回 {abort()}。
export function sse(path, body, onEvent, { onDone, onError } = {}) {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await fetch(API + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const blocks = buf.split('\n\n');
        buf = blocks.pop() || '';
        for (const block of blocks) {
          if (!block.trim()) continue;
          let evType = 'message', dataStr = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) evType = line.slice(6).trim();
            else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
          }
          let parsed = dataStr;
          try { parsed = JSON.parse(dataStr); } catch {}
          onEvent && onEvent(evType, parsed, dataStr);
        }
      }
      onDone && onDone();
    } catch (e) {
      if (e.name !== 'AbortError') onError && onError(e);
    }
  })();
  return { abort: () => ctrl.abort() };
}

// ---------- 纯工具 ----------
export function escHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}
export function escAttr(s) { return escHtml(s).replace(/`/g, '&#96;'); }

export function fmtDate(v) {
  if (!v) return '—';
  const d = new Date(v);
  if (isNaN(d)) return String(v);
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
}
export function fmtDateTime(v) {
  if (!v) return '—';
  const d = new Date(v);
  if (isNaN(d)) return String(v);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}
export function relTime(v) {
  if (!v) return '';
  const d = new Date(v); if (isNaN(d)) return '';
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 2592000) return `${Math.floor(diff / 86400)} 天前`;
  return fmtDate(v);
}
export function todayStr(offsetDays = 0) {
  const d = new Date(); d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}
export function debounce(fn, ms = 300) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
export function fmtBytes(n) {
  if (n == null) return '—';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}
