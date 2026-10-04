'use strict';

const $ = (selector) => document.querySelector(selector);
const state = { catalog: null, diagnosis: null, busy: false, view: 'workspace', viewRequest: 0 };
const viewNames = { workspace: '诊断工作台', knowledge: '规则知识', history: '诊断记录', evaluation: '评测结果' };
const statuses = {
  resolved: ['已完成诊断', 'success'], needs_info: ['待补充信息', 'warning'],
  needs_confirmation: ['身份有冲突，待确认', 'warning'],
  insufficient_evidence: ['证据不足', 'warning'], unsupported: ['超出支持范围', 'neutral']
};
const ruleNames = { R1: '活动范围与清仓排除', R2: '新客身份与原价门槛', R3: '优惠叠加限制', R4: '活动有效时间' };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function badge(text, tone = 'neutral') { return el('span', `badge badge-${tone}`, text); }
function button(text, classes, handler) {
  const node = el('button', classes, text);
  node.type = 'button';
  if (handler) node.addEventListener('click', handler);
  return node;
}
function money(value) {
  if (value === undefined || value === null || value === '') return '待确认';
  const number = Number(value);
  return Number.isFinite(number) ? `¥${number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : String(value);
}
function time(value) {
  if (!value) return '时间未提供';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)}（北京时间）`;
}
function backendLabel(backend) {
  if (backend === 'lexical-demo') return '本地关键词检索 · 演示';
  if (String(backend).toLowerCase().includes('lightrag')) return `LightRAG · ${backend}`;
  return backend ? `检索后端 · ${backend}` : '检索后端未提供';
}
function errorText(error) { return error instanceof Error ? error.message : '请求未完成，请稍后重试。'; }
function showGlobalError(message) {
  const node = $('#global-message');
  node.textContent = message || '';
  node.hidden = !message;
}
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  let data;
  try { data = await response.json(); } catch (_) { throw new Error('服务返回了无法读取的内容，请确认服务正常运行。'); }
  if (!response.ok) {
    let detail = data.detail || data.message || `请求失败（${response.status}）`;
    if (Array.isArray(detail)) detail = detail.map(item => `${(item.loc || []).filter(part => part !== 'body').join(' / ')}：${item.msg || '输入无效'}`).join('；');
    if (typeof detail === 'object') detail = JSON.stringify(detail);
    throw new Error(String(detail));
  }
  return data;
}
function loading(target, text) {
  const wrap = el('div', 'loading-state');
  wrap.setAttribute('role', 'status');
  const spinner = el('span', 'spinner');
  spinner.setAttribute('aria-hidden', 'true');
  wrap.append(spinner, el('p', '', text));
  target.replaceChildren(wrap);
}
function empty(target, title, text) {
  const wrap = el('div', 'empty-panel');
  wrap.append(el('h2', '', title), el('p', '', text));
  target.replaceChildren(wrap);
}
function loadError(target, error, retry) {
  const wrap = el('div', 'panel');
  const message = el('p', 'message error', errorText(error));
  message.setAttribute('role', 'alert');
  wrap.append(message, button('重新加载', 'button secondary', retry));
  target.replaceChildren(wrap);
}
function setBusy(busy) {
  state.busy = busy;
  const submit = $('#diagnose-button');
  submit.disabled = busy || !state.catalog;
  submit.textContent = busy ? '正在核验规则与金额…' : '开始诊断 ↗';
  $('#diagnosis-form').setAttribute('aria-busy', String(busy));
}

function renderCatalog(catalog) {
  state.catalog = catalog;
  $('#shop-name').textContent = catalog.shop?.name || '演示店铺';
  const cart = $('#cart-list');
  cart.replaceChildren();
  let total = 0;
  for (const item of catalog.cart || []) {
    const row = el('div', 'cart-item');
    const icon = el('span', 'product-icon', item.tags?.includes('clearance') ? '◇' : '△');
    icon.setAttribute('aria-hidden', 'true');
    const info = el('div', 'product-info');
    info.append(el('strong', '', item.name || item.sku));
    const meta = el('div', 'product-meta', `${item.sku} · ${item.collection === 'outdoor' ? '户外系列' : (item.collection || '未标明系列')}`);
    if (item.tags?.includes('clearance')) meta.append(el('span', 'tag', '清仓商品'));
    info.append(meta);
    const amount = el('div', 'cart-price');
    amount.append(el('strong', '', money(item.price)), el('small', '', `数量 × ${item.quantity}`));
    row.append(icon, info, amount);
    cart.append(row);
    total += Number(item.price) * Number(item.quantity);
  }
  if (!(catalog.cart || []).length) cart.append(el('p', 'muted', '暂无购物车商品。'));
  $('#cart-subtotal').textContent = money(total);
  const presets = $('#presets');
  presets.replaceChildren();
  for (const preset of catalog.presets || []) {
    const item = button(preset.label, 'preset', () => {
      $('#question').value = preset.question;
      $('#customer').value = preset.is_new_customer === true ? 'true' : preset.is_new_customer === false ? 'false' : 'unknown';
      if (preset.at) $('#at').value = preset.at;
      $('#question').focus();
    });
    presets.append(item);
  }
  if (!(catalog.presets || []).length) presets.append(el('span', 'muted', '输入问题即可开始。'));
  setBusy(false);
}
function subheading(title, note) {
  const section = el('div', 'subheading');
  section.append(el('h3', '', title));
  if (note) section.append(el('span', '', note));
  return section;
}
function evidenceBody(item) {
  const body = el('div', 'evidence-content');
  body.append(el('p', '', item.content || '该条证据未提供全文。'));
  body.append(el('small', '', `来源：${item.source || '未提供'}\n版本：${item.version || '未提供'}`));
  return body;
}
function renderEvidence(items, target) {
  for (const item of items) {
    const detail = el('details', 'evidence-item');
    detail.append(el('summary', '', `${item.id || ''} · ${item.title || '规则证据'}`), evidenceBody(item));
    target.append(detail);
  }
}
function renderDiagnosis(data, focus = true) {
  state.diagnosis = data;
  const result = $('#result-content');
  result.replaceChildren();
  const status = statuses[data.status] || [data.status || '状态未提供', 'neutral'];
  $('#result-state').className = `badge badge-${status[1]}`;
  $('#result-state').textContent = status[0];
  const answer = el('div', 'answer-block');
  answer.append(el('p', '', data.answer || '未返回诊断说明。'));
  result.append(answer);
  if (data.decision_context) {
    const context = data.decision_context;
    const identity = context.is_new_customer === true ? '新客户' : context.is_new_customer === false ? '老客户' : '尚未确认';
    const source = context.customer_source === 'user_confirmation' ? '你再次明确确认' : '本次表单提交';
    result.append(el('p', 'message info', `客户身份：${identity}（${source}）；订单时间：${context.at}。`));
  }
  const metadata = el('div', 'result-meta');
  metadata.append(badge(backendLabel(data.backend)), badge(`知识版本：${data.knowledge_snapshot || '未提供'}`));
  if (data.business_snapshot) metadata.append(badge(`业务版本：${typeof data.business_snapshot === 'string' ? data.business_snapshot : JSON.stringify(data.business_snapshot)}`));
  result.append(metadata);
  for (const warning of data.warnings || []) result.append(el('p', 'message info', warning));
  if (['needs_info', 'needs_confirmation'].includes(data.status) && (data.missing_fields || []).includes('is_new_customer')) {
    const continuation = el('section', 'continuation');
    continuation.append(el('h3', '', data.status === 'needs_confirmation' ? '请确认本次应使用的客户身份' : '补充客户身份，继续本次诊断'), el('p', '', '确认的身份将作为本次核验依据，原问题文字保留供追溯。将沿用原订单时间和购物车重新核验。'));
    for (const [value, label] of [[true, '确认是新客户'], [false, '确认是老客户']]) {
      continuation.append(button(label, 'button secondary', async () => {
        if (state.busy) return;
        setBusy(true);
        continuation.querySelectorAll('button').forEach(node => node.disabled = true);
        showGlobalError('');
        try {
          const next = await api(`/api/diagnoses/${encodeURIComponent(data.id)}/continue`, { method: 'POST', body: JSON.stringify({ is_new_customer: value }) });
          $('#customer').value = String(value);
          renderDiagnosis(next);
        } catch (error) {
          showGlobalError(errorText(error));
          continuation.querySelectorAll('button').forEach(node => node.disabled = false);
        } finally { setBusy(false); }
      }));
    }
    result.append(continuation);
  } else if ((data.missing_fields || []).length) {
    result.append(el('p', 'message info', `需要补充的信息：${data.missing_fields.join('、')}`));
  }
  if ((data.checks || []).length) {
    result.append(subheading('逐项规则核验', '条件未满足 ≠ 系统异常'));
    const checks = el('div', 'checks');
    for (const check of data.checks) {
      const type = ['pass', 'fail', 'unknown'].includes(check.result) ? check.result : 'unknown';
      const row = el('div', `check-row ${type}`);
      const symbol = el('span', 'check-symbol', type === 'pass' ? '✓' : type === 'fail' ? '−' : '?');
      symbol.setAttribute('aria-hidden', 'true');
      const text = el('div', 'check-detail');
      text.append(el('strong', '', `${check.rule_id} · ${ruleNames[check.rule_id] || '规则核验'}`), el('p', '', check.detail || check.reason_code || '未提供说明'));
      if (check.evidence_ids?.length) text.append(el('small', '', `关联依据：${check.evidence_ids.join('、')}`));
      row.append(symbol, text, el('span', 'check-label', type === 'pass' ? '满足条件' : type === 'fail' ? '不满足' : '待确认'));
      checks.append(row);
    }
    result.append(checks);
  }
  if ((data.plans || []).length) {
    result.append(subheading('优惠方案对比', `原价 ${money(data.subtotal)}`));
    const plans = el('div', 'plans');
    for (const plan of data.plans) {
      const recommended = data.recommended_plan === plan.id;
      const panel = el('div', `plan${recommended ? ' recommended' : ''}${plan.eligible === false ? ' unavailable' : ''}`);
      panel.append(badge(recommended ? `${plan.id} · 推荐方案` : plan.id, recommended ? 'success' : 'neutral'));
      panel.append(el('h4', '', plan.label || plan.id));
      panel.append(el('div', 'plan-amount', plan.eligible === false ? '不可用' : money(plan.total)));
      panel.append(el('small', '', plan.eligible === false ? '当前订单不满足使用条件' : plan.eligible === null ? '待确认资格，暂不推荐' : '优惠后应付金额'));
      plans.append(panel);
    }
    result.append(plans);
    if (!data.recommended_plan) result.append(el('p', 'muted', '当前没有可确认的推荐方案。'));
  }
  result.append(subheading('规则与证据', `${(data.evidence || []).length} 条来源 · 点击查看全文`));
  if (data.evidence?.length) renderEvidence(data.evidence, result);
  else result.append(el('p', 'muted', '本次未获得可引用的规则证据。'));
  if (data.trace?.length) {
    const trace = el('details', 'trace');
    const durations = data.trace.map(item => Number(item.duration_ms)).filter(Number.isFinite);
    trace.append(el('summary', '', `查看诊断过程 · ${data.trace.length} 个步骤${durations.length ? ` · 步骤耗时合计 ${durations.reduce((a, b) => a + b, 0).toFixed(1)} ms` : ''}`));
    const list = el('ol');
    for (const item of data.trace) {
      const row = el('li', '', `${item.step}${Number.isFinite(Number(item.duration_ms)) ? ` · ${Number(item.duration_ms).toFixed(1)} ms` : ''}`);
      if (item.detail) row.append(el('span', 'trace-detail', typeof item.detail === 'string' ? item.detail : JSON.stringify(item.detail)));
      list.append(row);
    }
    trace.append(list); result.append(trace);
  }
  if (data.id) renderFeedback(data, result);
  if (focus) {
    $('#result-panel').setAttribute('tabindex', '-1');
    $('#result-panel').focus({ preventScroll: true });
    if (window.innerWidth < 980) $('#result-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
function renderFeedback(data, result) {
  const wrap = el('section', 'feedback');
  wrap.append(el('p', '', '这次诊断对你有帮助吗？'));
  const label = el('label', 'sr-only', '反馈备注（选填）');
  label.htmlFor = 'feedback-comment';
  const input = el('input');
  input.id = 'feedback-comment'; input.maxLength = 2000; input.placeholder = '补充你的反馈（选填）';
  const actions = el('div', 'feedback-actions');
  const status = el('span', 'feedback-status');
  status.setAttribute('role', 'status');
  for (const [rating, title] of [['helpful', '有帮助 ✓'], ['incorrect', '结果有误']]) {
    actions.append(button(title, '', async () => {
      actions.querySelectorAll('button').forEach(node => node.disabled = true);
      status.textContent = '正在保存…';
      try {
        const response = await api(`/api/diagnoses/${encodeURIComponent(data.id)}/feedback`, { method: 'POST', body: JSON.stringify({ rating, comment: input.value.trim() }) });
        if (!response.saved) throw new Error('反馈尚未确认保存，请重试。');
        status.textContent = '反馈已保存，谢谢你的帮助。';
      } catch (error) { status.textContent = errorText(error); }
      finally { actions.querySelectorAll('button').forEach(node => node.disabled = false); }
    }));
  }
  wrap.append(label, input, actions, status, el('small', 'muted', `记录时间：${time(data.created_at)}`));
  result.append(wrap);
}
async function submitDiagnosis(event) {
  event.preventDefault();
  if (state.busy) return;
  const question = $('#question').value.trim();
  if (!question) { $('#question').focus(); showGlobalError('请先填写需要诊断的问题。'); return; }
  const rawCustomer = $('#customer').value;
  const payload = { question, at: $('#at').value.trim(), is_new_customer: rawCustomer === 'unknown' ? null : rawCustomer === 'true', cart: state.catalog.cart };
  showGlobalError('');
  setBusy(true);
  $('#result-state').className = 'badge badge-neutral';
  $('#result-state').textContent = '正在诊断';
  loading($('#result-content'), '正在检索规则、核验条件并计算方案…');
  try {
    const data = await api('/api/diagnoses', { method: 'POST', body: JSON.stringify(payload) });
    renderDiagnosis(data);
  } catch (error) {
    $('#result-state').textContent = '请求未完成';
    loadError($('#result-content'), error, () => $('#diagnosis-form').requestSubmit());
  } finally { setBusy(false); }
}
async function loadKnowledge(requestId) {
  const target = $('#knowledge-content'); loading(target, '正在读取规则知识…');
  try {
    const data = await api('/api/knowledge');
    if (requestId !== state.viewRequest) return;
    target.replaceChildren();
    if (!data.items?.length) return empty(target, '暂无规则知识', '当前知识快照未包含可用规则。');
    for (const item of data.items) {
      const card = el('article', 'panel knowledge-card');
      card.append(badge(`${item.id} · ${item.version || '版本未提供'}`, 'success'), el('h2', '', item.title), evidenceBody(item));
      target.append(card);
    }
  } catch (error) { if (requestId === state.viewRequest) loadError(target, error, () => navigate('knowledge')); }
}
async function loadHistory(requestId) {
  const target = $('#history-content'); loading(target, '正在读取诊断记录…');
  try {
    const data = await api('/api/diagnoses');
    if (requestId !== state.viewRequest) return;
    target.replaceChildren();
    if (!data.items?.length) return empty(target, '还没有诊断记录', '在诊断工作台提交一个问题，完整结果会自动保存在这里。');
    for (const item of data.items) {
      const status = statuses[item.status] || [item.status, 'neutral'];
      const card = button('', 'history-card', async () => {
        card.disabled = true; showGlobalError('');
        try {
          const detail = await api(`/api/diagnoses/${encodeURIComponent(item.id)}`);
          navigate('workspace'); renderDiagnosis(detail);
          if (detail.question) $('#question').value = detail.question;
          if (detail.at) $('#at').value = detail.at;
          if ('is_new_customer' in detail) $('#customer').value = detail.is_new_customer === null ? 'unknown' : String(detail.is_new_customer);
          if (detail.cart) renderCatalog({ ...state.catalog, cart: detail.cart });
        } catch (error) { showGlobalError(errorText(error)); }
        finally { card.disabled = false; }
      });
      card.append(el('strong', '', item.question || '诊断记录'), badge(status[0], status[1]), el('p', '', item.answer || '暂无诊断说明'), el('time', '', time(item.created_at)), el('span', 'open-history', '查看完整诊断 ↗'));
      target.append(card);
    }
  } catch (error) { if (requestId === state.viewRequest) loadError(target, error, () => navigate('history')); }
}
async function loadEvaluation(requestId) {
  const target = $('#evaluation-content'); loading(target, '正在读取实际评测结果…');
  try {
    const data = await api('/api/evaluation');
    if (requestId !== state.viewRequest) return;
    target.replaceChildren();
    const panel = el('section', 'panel evaluation-panel');
    panel.append(badge(data.status === 'completed' ? '已运行' : data.status === 'not_run' ? '尚未运行' : (data.status || '状态未提供'), data.status === 'completed' ? 'success' : 'warning'));
    panel.append(el('h2', '', data.status === 'completed' ? '本次验证结果' : '暂无已确认的评测结果'));
    panel.append(el('p', '', data.scope || '服务未提供本次评测范围。'));
    if (data.message) panel.append(el('p', '', data.message));
    if (data.backend) panel.append(badge(backendLabel(data.backend)));
    if (data.generated_at) panel.append(el('p', 'muted', `运行时间：${time(data.generated_at)}`));
    target.append(panel);
    if (data.status === 'completed' && data.summary) {
      const stats = el('div', 'evaluation-summary');
      for (const [key, label] of [['total', '实际用例'], ['passed', '通过'], ['failed', '未通过']]) {
        if (data.summary[key] === undefined) continue;
        const stat = el('div', 'evaluation-stat');
        stat.append(el('strong', '', data.summary[key]), el('span', '', label)); stats.append(stat);
      }
      target.append(stats);
      const latency = [];
      if (data.summary.p50_ms !== undefined && data.summary.p50_ms !== null) latency.push(`P50 ${Number(data.summary.p50_ms).toFixed(1)} ms`);
      if (data.summary.p95_ms !== undefined && data.summary.p95_ms !== null) latency.push(`P95 ${Number(data.summary.p95_ms).toFixed(1)} ms`);
      if (latency.length) target.append(el('p', 'message info', `本次执行耗时：${latency.join(' · ')}。仅反映当前本地测试环境。`));
    }
    if (data.cases?.length) {
      const cases = el('section', 'panel evaluation-panel'); cases.append(el('h2', '', '逐项检查'));
      const list = el('ul', 'evaluation-list');
      for (const item of data.cases) {
        const row = el('li');
        row.append(badge(item.passed === true ? '通过' : item.passed === false ? '未通过' : '未确认', item.passed === true ? 'success' : item.passed === false ? 'error' : 'neutral'), el('span', '', ` ${item.id || ''} · ${item.question || item.name || '检查用例'}`));
        if (item.expected_status || item.actual_status) row.append(el('small', '', `预期：${statuses[item.expected_status]?.[0] || item.expected_status || '未提供'} · 实际：${statuses[item.actual_status]?.[0] || item.actual_status || '未提供'}`));
        if (item.details) row.append(el('small', '', typeof item.details === 'string' ? item.details : JSON.stringify(item.details)));
        list.append(row);
      }
      cases.append(list); target.append(cases);
    }
    const raw = el('details', 'trace'); raw.append(el('summary', '', '查看评测原始记录'), el('pre', 'raw-data', JSON.stringify(data, null, 2))); target.append(raw);
  } catch (error) { if (requestId === state.viewRequest) loadError(target, error, () => navigate('evaluation')); }
}
function navigate(view) {
  if (!viewNames[view]) view = 'workspace';
  state.view = view;
  const requestId = ++state.viewRequest;
  document.querySelectorAll('.view').forEach(node => node.hidden = node.id !== `view-${view}`);
  document.querySelectorAll('.nav-item').forEach(node => {
    const active = node.dataset.view === view;
    node.classList.toggle('active', active);
    if (active) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
  });
  $('#breadcrumb-current').textContent = viewNames[view];
  document.title = `${viewNames[view]} · 商策 CommerceOps`;
  if (window.location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
  if (view === 'knowledge') loadKnowledge(requestId);
  if (view === 'history') loadHistory(requestId);
  if (view === 'evaluation') loadEvaluation(requestId);
}
async function initialize() {
  setBusy(false);
  const results = await Promise.allSettled([api('/api/health'), api('/api/catalog')]);
  if (results[0].status === 'fulfilled') {
    const health = results[0].value;
    $('#backend-badge').textContent = backendLabel(health.backend);
    $('#backend-badge').className = 'badge badge-success';
    $('#backend-badge').title = `服务状态：${health.status} · 版本：${health.version}`;
  } else {
    $('#backend-badge').textContent = '服务连接失败';
    $('#backend-badge').className = 'badge badge-error';
  }
  if (results[1].status === 'fulfilled') renderCatalog(results[1].value);
  else {
    showGlobalError(`无法载入演示订单：${errorText(results[1].reason)}`);
    loadError($('#cart-list'), results[1].reason, initialize);
    $('#presets').replaceChildren(el('span', 'muted', '演示问题暂不可用。'));
  }
  navigate(window.location.hash.slice(1) || 'workspace');
}
$('#diagnosis-form').addEventListener('submit', submitDiagnosis);
for (const nav of document.querySelectorAll('.nav-item')) nav.addEventListener('click', () => navigate(nav.dataset.view));
$('.brand').addEventListener('click', event => { event.preventDefault(); navigate('workspace'); });
$('#refresh-history').addEventListener('click', () => navigate('history'));
window.addEventListener('hashchange', () => navigate(window.location.hash.slice(1)));
initialize();
