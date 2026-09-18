// State machines stay independent of DOM/network for deterministic race guards.
export class ProbeCoordinator {
  constructor({probe, render}) {
    Object.assign(this, {probe, render, generation:0, value:'', result:null, active:true, controller:null, lastSaved:null});
  }
  invalidate() {
    this.generation++;
    this.controller?.abort();
    this.controller = null;
    this.result = null;
    if (this.active) this.render(null);
  }
  edit(value) {
    if (this.value === value) return;
    this.value = value;
    this.invalidate();
  }
  saved({value, generation}) {
    if (!this.active || generation !== this.generation || value !== this.value) return;
    const identity = `${generation}:${value}`;
    if (this.lastSaved === identity) return;
    this.lastSaved = identity; // Deduplicate BEFORE aborting the live probe.
    this.invalidate();
    this.run();
  }
  manual() { this.invalidate(); this.run(); }
  async run() {
    const generation = this.generation;
    const controller = this.controller = new AbortController();
    try {
      const result = await this.probe({signal:controller.signal});
      if (!this.active || controller.signal.aborted || generation !== this.generation) return;
      this.result = result;
      this.render(result);
    } catch (error) {
      if (this.active && !controller.signal.aborted && generation === this.generation) {
        this.result = {transport_error:error.message};
        this.render(this.result);
      }
    }
  }
  unmount() { this.active = false; this.invalidate(); }
}

export function describeProbe(result) {
  if (result.transport_error) return `测试请求未完成：${result.transport_error}`;
  if (result.ok) return `设置已保存，嵌入测试通过（${result.model_id ?? '当前模型'} · ${result.dim} 维 · ${result.elapsed_ms} ms）`;
  const code = result.error_code || '';
  const message = /^http_(401|403)$/.test(code) ? '鉴权失败' : code === 'http_404' ? '端点或模型不存在'
    : code === 'http_429' ? '请求过于频繁' : /^http_5\d\d$/.test(code) ? '供应商返回错误'
    : code === 'timeout' ? '本次测试超时（15 秒），不代表模型不支持'
    : code.startsWith('network:') ? '连接失败' : code === 'invalid_response' ? '响应无法解析' : '供应商未通过本次测试';
  return `设置已保存，本次嵌入测试失败：${message}`;
}

export function describeAlignment(status) {
  const job = status.job || {state:'idle'}, totals = status.totals || {};
  const common = {disabled:false, poll:false, action:'重新检查并对齐待处理向量'};
  if (!status.route?.available) {
    const reasons = {db_error:'配置暂时无法读取', no_model:'未选择模型', provider_missing:'模型未绑定可用供应商', provider_no_key:'供应商缺少 API Key', env_incomplete:'环境变量的端点或 Key 不完整', provider_format_anthropic:'Anthropic 格式不支持此嵌入请求', url_invalid:'端点地址无效'};
    return {...common, disabled:true, action:null, text:`未配置可用嵌入服务（${reasons[status.route?.reason] || '请检查模型、格式与密钥'}）`};
  }
  if (job.state === 'running') return job.lease_expired
    ? {...common, action:'继续对齐', text:'上一轮对齐已中断'}
    : {...common, disabled:true, poll:true, text:`正在重新对齐：${job.done}/${job.total}，失败 ${job.failed}`};
  if (job.state === 'done') return {...common, text:`本轮已结束：成功 ${job.done} 条，失败 ${job.failed} 条${job.skipped > 0 ? `；另有 ${job.skipped} 条因内容或状态变化跳过；待处理数量以重新检查结果为准` : ''}`};
  if (job.state === 'target_changed') return {...common, text:'嵌入模型已更换，上一轮已中止'};
  if (totals.pending_rows === 0) return {...common, action:null, text:`向量已对齐（${totals.current} 条）`};
  return {...common, text:`有 ${totals.pending_rows} 条待处理（约 ${totals.pending_characters} 字符）`};
}

let pageSequence = 0;
export function mountEmbeddingPanel(root, {configRoot, request, errorMessage, confirmDialog, toast}) {
  const pageToken = ++pageSequence;
  let active = true, statusGeneration = 0, statusController, timer, rebuildBusy = false;
  root.innerHTML = `<div class="section-title mt16">向量对齐</div>
    <p data-embedding-status role="status" aria-live="polite">正在检查向量状态…</p>
    <div class="toolbar"><button class="btn btn-primary" data-align disabled>重新检查并对齐待处理向量</button>
    <button class="btn btn-secondary" data-probe disabled>测试嵌入</button></div>
    <p class="muted text-sm">测试会发送一条简短文本，可能产生少量费用。向量对齐会重新生成待处理向量，费用由当前供应商结算。</p>
    <div data-diagnostic aria-live="polite"></div>`;
  const statusText = root.querySelector('[data-embedding-status]');
  const align = root.querySelector('[data-align]'), test = root.querySelector('[data-probe]');
  const diagnostic = root.querySelector('[data-diagnostic]');
  const input = configRoot.querySelector('[data-key="default_embedding_model"]');
  const receipt = async (path, options) => {
    const response = await request(path, options);
    if (response.status === 404) { if (active && !options?.signal?.aborted) root.hidden = true; return null; }
    const body = await response.json();
    if (!response.ok || body.error) throw new Error(errorMessage(body, response.status));
    return body;
  };
  const renderProbe = result => {
    diagnostic.replaceChildren();
    test.textContent = '测试嵌入';
    if (!result) return;
    const banner = document.createElement('p');
    banner.className = result.ok ? 'banner banner-info' : 'banner banner-warn';
    banner.textContent = describeProbe(result);
    diagnostic.append(banner);
    if (result.transport_error) return;
    const details = document.createElement('details'), summary = document.createElement('summary');
    summary.textContent = '展开诊断'; details.append(summary);
    for (const [key, value] of Object.entries(result)) {
      const row = document.createElement('p');
      row.className = 'mono text-sm'; row.style.overflowWrap = 'anywhere';
      row.textContent = `${key}: ${value === null ? '—' : String(value).slice(0,key === 'upstream_message' ? 200 : undefined)}`;
      details.append(row);
      if (key === 'upstream_message' && typeof value === 'string' && value.length > 200) {
        const more = document.createElement('details'), label = document.createElement('summary'), full = document.createElement('p');
        label.textContent = '展开完整摘要'; full.textContent = value; full.style.overflowWrap = 'anywhere'; more.append(label,full); details.append(more);
      }
    }
    const copy = document.createElement('button'); copy.className = 'btn btn-secondary'; copy.textContent = '复制诊断';
    copy.onclick = async () => { try { await navigator.clipboard.writeText(JSON.stringify(result,null,2)); toast('诊断已复制'); } catch { toast('复制失败，请从展开诊断中选择文本','err'); } };
    diagnostic.append(details,copy);
  };
  const coordinator = new ProbeCoordinator({render:renderProbe, probe:async ({signal}) => {
    test.textContent = '测试中…';
    const body = await receipt('/admin/embedding-probe',{method:'POST',body:{},signal});
    if (body === null) throw new Error('当前后端尚不支持嵌入探针');
    return body;
  }});
  coordinator.edit(input?.value || '');
  const stamp = () => { if (input) input.embeddingSaveContext = {generation:coordinator.generation,pageToken}; };
  stamp();
  const changed = () => { coordinator.edit(input?.value || ''); stamp(); };
  input?.addEventListener('input',changed); input?.addEventListener('change',changed);
  const refresh = async () => {
    clearTimeout(timer); statusController?.abort();
    const generation = ++statusGeneration, controller = statusController = new AbortController();
    try {
      const status = await receipt('/admin/embedding-status',{signal:controller.signal});
      if (!active || generation !== statusGeneration || status === null) return null;
      const view = describeAlignment(status);
      root.hidden = false; statusText.textContent = view.text;
      align.hidden = !view.action; align.textContent = view.action || ''; align.disabled = view.disabled || rebuildBusy;
      test.disabled = !status.route?.available;
      if (view.poll) timer = setTimeout(refresh,2000);
      return status;
    } catch (error) {
      if (active && !controller.signal.aborted && generation === statusGeneration) { statusText.textContent = error.message; align.disabled = true; }
      return null;
    }
  };
  const saved = event => {
    const detail = event.detail || {};
    if (detail.key !== 'default_embedding_model' || detail.pageToken !== pageToken) return;
    coordinator.saved(detail); stamp(); refresh();
  };
  document.addEventListener('kiwi:config-saved',saved);
  test.onclick = () => { coordinator.manual(); stamp(); };
  align.onclick = async () => {
    if (rebuildBusy) return;
    rebuildBusy = true; align.disabled = true;
    try {
      const status = await refresh();
      if (!active || !status?.route?.available) return;
      const {pending_rows:count,pending_characters:characters} = status.totals;
      if (!await confirmDialog({title:'向量对齐',message:`当前待处理 ${count} 条（约 ${characters} 字符），将按当前嵌入模型重新生成，费用由当前供应商结算。继续？`,okText:'开始对齐'})) return;
      if (!active) return;
      await receipt('/admin/embedding-rebuild',{method:'POST',body:{scope:'stale'}});
    } catch (error) { if (active) toast(error.message,'err'); }
    finally { rebuildBusy = false; if (active) refresh(); }
  };
  refresh();
  return {
    invalidate() { coordinator.invalidate(); stamp(); if (active) refresh(); },
    unmount() {
      active = false; coordinator.unmount(); statusGeneration++; statusController?.abort(); clearTimeout(timer);
      document.removeEventListener('kiwi:config-saved',saved);
      input?.removeEventListener('input',changed); input?.removeEventListener('change',changed);
      if (input) delete input.embeddingSaveContext;
    },
  };
}
