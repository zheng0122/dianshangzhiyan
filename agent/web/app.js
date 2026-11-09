/* 电商智研 前端（原生 JS，无需构建）。后端同源 /api，或用 ?api=http://host:8000 指定 */
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = s => esc(s).replace(/\n/g, '<br>');
function md(src) {  // 极简 Markdown：标题/粗体/列表/段落（先转义，安全）
  const inline = t => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`(.+?)`/g, '<code>$1</code>');
  let out = '', list = null; const close = () => { if (list) { out += `</${list}>`; list = null; } };
  for (const ln of String(src ?? '').replace(/\r/g, '').split('\n')) {
    let m;
    if ((m = ln.match(/^\s*#{1,6}\s+(.*)/))) { close(); out += `<h4 style="margin:8px 0 4px">${inline(m[1])}</h4>`; }
    else if ((m = ln.match(/^\s*[-*•]\s+(.*)/))) { if (list !== 'ul') { close(); out += '<ul>'; list = 'ul'; } out += `<li>${inline(m[1])}</li>`; }
    else if ((m = ln.match(/^\s*\d+[.、)]\s+(.*)/))) { if (list !== 'ol') { close(); out += '<ol>'; list = 'ol'; } out += `<li>${inline(m[1])}</li>`; }
    else if (!ln.trim()) { close(); out += '<div style="height:6px"></div>'; }
    else { close(); out += `<div>${inline(ln)}</div>`; }
  }
  close(); return out;
}
const API = (window.API_BASE || new URLSearchParams(location.search).get('api') || '').replace(/\/$/, '');
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } }
};
const S = { health: {}, mock: false, chat: [], form: {}, result: null, plans: null, diag: null, custReplies: {}, busy: false };

/* ---------- 工具 ---------- */
function toast(t) { const el = $('#toast'); el.textContent = t; el.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('on'), 1800); }
async function copy(t) {
  try { await navigator.clipboard.writeText(t); toast('已复制'); } catch (e) {
    const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); toast('已复制'); } catch (e2) { toast('复制失败'); } ta.remove();
  }
}
async function api(path, body, opt = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (opt.admin) {
    const tk = LS.get('admin_token', '');
    if (!tk) throw new Error('请先在「自动发布」页填写管理口令');
    headers['X-Admin-Token'] = tk;
  }
  let r;
  try {
    r = await fetch(API + path, { method: opt.method || (body ? 'POST' : 'GET'), headers, body: body ? JSON.stringify(body) : undefined });
  } catch (e) { throw new Error('无法连接服务，请确认后端已启动'); }
  let d = null; try { d = await r.json(); } catch (e) { /* ignore */ }
  if (!r.ok) throw new Error((d && (d.detail || d.message)) ? (typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail)) : ('请求失败 ' + r.status));
  return d;
}
function logAct(agent, text) {
  const log = LS.get('log', []); log.unshift({ agent, text, t: Date.now() }); LS.set('log', log.slice(0, 30));
  const c = LS.get('cnt', { all: 0, chuang: 0, wen: 0 }); c.all++; if (c[agent] !== undefined) c[agent]++; LS.set('cnt', c);
}
function ago(t) { const m = Math.max(0, Math.round((Date.now() - t) / 60000)); return m < 1 ? '刚刚' : m < 60 ? m + '分钟前' : m < 1440 ? Math.round(m / 60) + '小时前' : Math.round(m / 1440) + '天前'; }
const loading = t => `<div class="typing"><span class="spin"></span>${esc(t)}</div>`;

/* ---------- 消息中心（红点 / 通知条）---------- */
const MSGS = { load: () => LS.get('msgs', []), save: l => LS.set('msgs', l.slice(0, 80)) };
const unreadCount = () => MSGS.load().filter(m => !m.read).length;
const badgeHtml = () => { const n = unreadCount(); return n ? `<i class="bdg">${n > 9 ? '9+' : n}</i>` : ''; };
function updateBadges() {
  const b = $('#topbar [data-a=bell]'); if (b) b.innerHTML = '🔔' + badgeHtml();
  const t = $('#tabbar a[href="#/msg"]'); if (t) { const o = t.querySelector('.bdg'); if (o) o.remove(); const h = badgeHtml(); if (h) t.insertAdjacentHTML('beforeend', h); }
}
function showNotice(m) {
  const n = $('#notice'); if (!n) return;
  n.dataset.id = m.id; n.innerHTML = `<b>🔔 ${esc(m.title)}</b><div class="mut">${esc(m.summary || '点击查看')}</div>`;
  n.classList.add('on'); clearTimeout(showNotice.t); showNotice.t = setTimeout(() => n.classList.remove('on'), 5000);
}
function pushMsg(m, read) {
  const list = MSGS.load(); const msg = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5), t: Date.now(), read: !!read, ...m };
  list.unshift(msg); MSGS.save(list); updateBadges();
  if (!read) showNotice(msg);
  if (parse().name === 'msg') render();
}
function nav(h) { if (location.hash === h) render(); else location.hash = h; }
function openMsg(id) {
  const list = MSGS.load(), m = list.find(x => x.id === id); if (!m) return;
  m.read = true; MSGS.save(list); updateBadges(); $('#notice').classList.remove('on');
  const p = m.payload || {};
  switch (m.kind) {
    case 'wen': S.chat = [{ role: 'user', text: p.q }, { role: 'assistant', text: p.a, sugg: [] }]; nav('#/wen/chat'); break;
    case 'chuang': S.result = p.result; nav('#/chuang/result'); break;
    case 'da': S.plans = p.plans; S.daf = p.f || S.daf; S.dabot = p.bot || '1'; nav('#/da'); break;
    case 'fu': nav('#/fu/chat?id=' + p.id); break;
    case 'xi': S.range = p.range; S.diag = { r: p.range, d: p.d }; nav('#/xi'); break;
    case 'server': nav('#/publish'); break;
    default: nav('#/home');
  }
}
async function pollEvents() {
  if (!LS.get('admin_token', '')) return;
  try {
    const last = LS.get('last_ev', null);
    const evs = await api('/api/notifications?after=' + (last || 0), null, { admin: true });
    let max = last || 0; const dayAgo = Date.now() / 1000 - 86400;
    for (const e of evs) {
      max = Math.max(max, e.id); if (last === null && e.ts < dayAgo) continue;
      pushMsg({ agent: 'sys', kind: 'server', title: e.title, summary: e.body, payload: { ref: e.ref } }, S.cur === 'publish');
    }
    LS.set('last_ev', max);
  } catch (e) { /* 口令无效或后端未启动时忽略 */ }
}
const todayStr = () => { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
const fmtNum = v => (v === null || v === undefined) ? '—' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
const fmtDelta = m => (m.delta === null || m.delta === undefined) ? '' : (m.delta > 0 ? '+' : '') + m.delta + (m.unit === 'pp' ? 'pp' : '%');

/* ---------- 数据 ---------- */
const AG = [
  { k: 'wen', name: '云问', tag: '开店咨询', desc: '3秒解答开店疑惑，政策解读·运营指导', ic: '💬', g: 'linear-gradient(135deg,#A18CD1,#FBC2EB)', bg: '#EDE7FF', c: '#8B5CF6' },
  { k: 'chuang', name: '云创', tag: '内容生成', desc: '30秒生成文案·脚本·卖点，全平台适配', ic: '✨', g: 'linear-gradient(135deg,#667EEA,#764BA2)', bg: '#E8F0FF', c: '#0066FF' },
  { k: 'da', name: '云搭', tag: 'AI导购', desc: '从模糊需求到可视化搭配推荐', ic: '👗', g: 'linear-gradient(135deg,#F093FB,#F5576C)', bg: '#FFE9EE', c: '#E0446A' },
  { k: 'fu', name: '云服', tag: '智能客服', desc: '7×24小时全天候，3秒响应客户', ic: '🎧', g: 'linear-gradient(135deg,#4FACFE,#00C6C0)', bg: '#E6F7F0', c: '#10B981' },
  { k: 'xi', name: '云析', tag: '数据分析', desc: '上传数据即得图表+AI诊断建议', ic: '📊', g: 'linear-gradient(135deg,#FA709A,#FEA140)', bg: '#FEF3E6', c: '#F59E0B' }
];
const agent = k => AG.find(a => a.k === k);
const DOMAINS = [
  ['开店咨询', '平台选择·开店流程', '🏪', '#EDE7FF', '新手开店应该怎么选平台、走哪些开店流程？'],
  ['平台政策解读', '规则解读·申诉方法', '🛡️', '#E8F0FF', '电商平台常见的违规类型有哪些，被处罚后如何申诉？'],
  ['商品运营指导', '标题优化·转化提升', '📈', '#E6F7F0', '怎样优化商品标题和主图来提升转化率？'],
  ['开店避坑指南', '常见误区·风险提醒', '⚠️', '#FFF1E0', '新手开店最容易踩的坑有哪些？'],
  ['预算规划', '资金分配·成本核算', '💰', '#FFE9EE', '开一家网店的启动资金应该怎么分配和核算？'],
  ['选品建议', '爆款发现·利润分析', '💡', '#FFF8DC', '新手选品有哪些方法，怎么判断一个商品有没有利润空间？']
];
const HOT = ['抖音小店怎么入驻？', '新手选品技巧？', '如何避免违规？'];
const TYPES = ['小红书文案', '朋友圈文案', '抖音短视频脚本', '直播口播', '商品卖点'];
const STYLES = ['潮流种草', '专业可信', '温暖亲切', '简洁有力', '幽默风趣'];
const TPL = [
  ['🍓', '水果外送', { type: '小红书文案', product: '新鲜水果礼盒', points: '当季现摘、冷链配送、新鲜到家', audience: '家庭用户', style: '温暖亲切' }],
  ['⛺', '户外装备', { type: '小红书文案', product: '轻量户外折叠椅', points: '便携轻巧、承重稳定、收纳方便', audience: '露营爱好者', style: '专业可信' }],
  ['💄', '美妆护肤', { type: '小红书文案', product: '保湿面霜', points: '温和配方、保湿滋润、质地清爽', audience: '熬夜党女性', style: '潮流种草' }]
];
const SCENES = [['通勤', '职场精英风', '💼'], ['露营', '户外自然风', '⛺'], ['约会', '浪漫甜美风', '💕'], ['运动', '活力运动风', '🏃'], ['旅行', '轻装出行风', '✈️'], ['宿舍生活', '居家舒适风', '🏠']];
const PSTYLES = ['简约', '轻奢', '休闲', '高性价比'];
const CUST = [
  { id: 1, name: '王小明', tag: '问尺码', tc: 'b', st: '已解决', time: '2分钟前', unread: 0, bg: '#E8F0FF', c: '#0066FF',
    msgs: [['c', '你好，想咨询一下'], ['c', '这款T恤的S码适合多大身材？']] },
  { id: 2, name: '李美丽', tag: '问发货', tc: 'g', st: '紧急', time: '15分钟前', unread: 1, bg: '#E6F7F0', c: '#10B981',
    msgs: [['c', '客服您好'], ['c', '我昨天下单了，请问什么时候发货？'], ['a', '您好，稍等，我帮您查询一下订单状态～'], ['c', '我的订单什么时候能发货呢？']] },
  { id: 3, name: '张三丰', tag: '物流', tc: 'o', st: '等待中', time: '1小时前', unread: 0, bg: '#FFF1E0', c: '#F59E0B',
    msgs: [['c', '物流已经3天没动静了，这是怎么回事？']] },
  { id: 4, name: '陈淑芬', tag: '申请退款', tc: 'r', st: '', time: '2小时前', unread: 3, bg: '#FFE9E9', c: '#EF4444',
    msgs: [['c', '这件衣服质量有问题，我要退货退款！']] },
  { id: 5, name: '赵志远', tag: '投诉', tc: 'r', st: '紧急', time: '3小时前', unread: 3, bg: '#EDE7FF', c: '#8B5CF6',
    msgs: [['c', '这什么破玩意！东西跟图片差这么多！投诉你们！']] }
];
const RANGES = {
  '近7日': { days: 7, k: 1, pts: [8.2, 9.1, 8.6, 10.3, 11.2, 12.4, 12.9] },
  '近30日': { days: 30, k: 4.1, pts: [38, 41, 40, 44, 47, 46, 50, 52, 54, 56] },
  '近90日': { days: 90, k: 12.2, pts: [110, 120, 118, 130, 138, 142, 150, 156, 160, 168, 172, 180] }
};
function metricsFor(r) {
  const k = RANGES[r].k;
  return [
    ['销售额', '¥' + Math.round(128430 * k).toLocaleString(), '+12.3%', 1],
    ['订单数', Math.round(1247 * k).toLocaleString(), '+8.5%', 1],
    ['转化率', '3.42%', '+0.8%', 1],
    ['客单价', '¥102.9', '+3.2%', 1],
    ['复购率', '28.6%', '+5.1%', 1],
    ['ROI', '4.2x', '+0.3x', 1]
  ];
}

/* ---------- 路由 ---------- */
const TABS = [['home', '首页', '🏠'], ['work', '工作台', '🧰'], ['msg', '消息', '💬'], ['me', '我的', '👤']];
function parse() {
  const h = (location.hash || '#/home').replace(/^#\/?/, '');
  const [path, q] = h.split('?'); const parts = path.split('/').filter(Boolean);
  return { name: parts[0] || 'home', sub: parts[1] || '', q: new URLSearchParams(q || '') };
}
function go(h) { location.hash = h; }
const FULL = new Set(['wen/chat', 'chuang/new', 'chuang/result', 'fu/chat']);
const TABOF = { data: 'me', diagnose: 'me', home: 'home', wen: 'home', chuang: 'home', da: 'home', fu: 'home', xi: 'home', work: 'work', publish: 'work', msg: 'msg', me: 'me' };
function chrome(route, title, back) {
  $('#topbar').innerHTML = `<div class="tl"><button class="ib" data-a="${back ? 'back' : 'menu'}">${back ? '‹' : '☰'}</button></div>
    <div style="text-align:center;flex:1">${esc(title)}${S.mock ? `<span class="mockchip">${S.mockAll ? '演示模式' : '部分演示'}</span>` : ''}</div>
    <button class="ib" data-a="bell">🔔${badgeHtml()}</button>`;
  const key = route.name + (route.sub ? '/' + route.sub : '');
  $('#app').classList.toggle('hide-tab', FULL.has(key));
  const on = TABOF[route.name] || 'home';
  $('#tabbar').innerHTML = TABS.map(t => `<a href="#/${t[0]}" class="${t[0] === on ? 'on' : ''}"><b>${t[2]}</b>${t[1]}${t[0] === 'msg' ? badgeHtml() : ''}</a>`).join('');
}
function view(html, nopad) { const v = $('#view'); v.className = nopad ? 'nopad' : ''; v.innerHTML = html; v.scrollTop = 0; }

const R = {};
async function render() {
  const rt = parse(); const key = rt.name + (rt.sub ? '/' + rt.sub : '');
  S.cur = key;
  const fn = R[key] || R[rt.name] || R.home;
  try { await fn(rt); } catch (e) { view(`<div class="err">页面出错：${esc(e.message)}</div>`); }
}
window.addEventListener('hashchange', render);

/* ---------- 页面：首页 ---------- */
R.home = async rt => {
  chrome(rt, '电商智研');
  const draw = sm => {
    const real = sm && sm.has_data, L = real ? sm.latest : null;
    const label = real ? (sm.latest_date === todayStr() ? '今日经营概览' : '最近一日经营概览 · ' + sm.latest_date.slice(5)) : '今日经营概览';
    view(`<div class="hero" style="padding:20px">
      <div style="font-size:13px;font-weight:500">${label} ${real ? '<span class="mockchip" style="background:#e6f7f0;color:#0b8a5f">真实数据</span>' : '<span class="mockchip">示例数据</span>'}</div>
      <div class="stats"><div><b>${real ? fmtNum(L.visitors) : '1,234'}</b><span>👁 访客</span></div><div><b>${real ? fmtNum(L.orders) : '56'}</b><span>🛒 订单</span></div><div><b>${real ? (L.gmv_display || '—') : '¥8.2k'}</b><span>📈 GMV</span></div></div>
      ${real ? `<div style="font-size:11px;opacity:.85;margin-top:10px">近7日销售额 ${sm.total_gmv_display || '—'} · <span data-a="go" data-h="#/data" style="text-decoration:underline">管理数据</span></div>`
             : `<button class="btn-w" style="margin-top:12px;padding:6px 14px;font-size:12px" data-a="go" data-h="#/data">导入真实数据 ›</button>`}</div>
    <h2>智能助手</h2><div class="mut" style="margin-bottom:14px">五大AI技能，全链路覆盖电商经营</div>
    ${AG.map(a => `<div class="agent" data-a="go" data-h="#/${a.k}">
      <div class="ico" style="background:${a.g}">${a.ic}</div>
      <div><div class="nm">${a.name}<span class="badge" style="background:${a.bg};color:${a.c}">${a.tag}</span></div><div class="ds">${a.desc}</div></div>
      <div class="ch">›</div></div>`).join('')}`);
  };
  draw(S.sum || null);
  try { S.sum = await api('/api/data/summary?days=7'); if (S.cur === 'home') draw(S.sum); } catch (e) { /* 后端不可用时保留示例 */ }
};

/* ---------- 云问 ---------- */
R.wen = rt => {
  chrome(rt, '云问 · 开店咨询', true);
  view(`<div class="hero"><h1>🤖 云问 AI 顾问</h1><p>专业开店顾问，7×24小时在线</p>
      <div class="tags"><span>开店全流程</span><span>平台政策</span><span>运营指导</span><span>选品建议</span></div>
      <button class="btn-w" data-a="go" data-h="#/wen/chat">开始咨询 ›</button></div>
    <h2>六大专业领域</h2><div class="mut" style="margin-bottom:12px">覆盖开店全流程，专业问题即问即答</div>
    <div class="grid2">${DOMAINS.map((d, i) => `<div class="dom" data-a="ask" data-i="${i}"><i style="background:${d[3]}">${d[2]}</i><div><b>${d[0]}</b><span>${d[1]}</span></div></div>`).join('')}</div>
    <h2>热门问题</h2><div class="chips" style="margin-top:8px">${HOT.map(h => `<span class="chip" data-a="askq" data-q="${esc(h)}">${esc(h)}</span>`).join('')}</div>`);
};
function renderChat() {
  const box = $('#msgs'); if (!box) return;
  box.innerHTML = (S.chat.length ? '' : `<div class="empty">你好，我是云问，请问有什么开店问题？</div>`) +
    S.chat.map((m, i) => m.role === 'user' ? `<div class="bub u">${fmt(m.text)}</div>` :
      `<div class="bub a">${answerHtml(m.text)}<div class="row" style="margin-top:6px"><button class="btn sm gray" data-a="copytxt" data-i="${i}">复制回复</button><button class="btn sm gray" data-a="savetxt" data-i="${i}">保存</button></div>${(m.sugg && m.sugg.length && i === S.chat.length - 1) ? `<div class="chips" style="margin-top:8px">${m.sugg.map(q => `<span class="chip" data-a="askq2" data-q="${esc(q)}">${esc(q)}</span>`).join('')}</div>` : ''}</div>`).join('') +
    (S.busy ? loading('云问正在思考…') : '');
  box.scrollTop = box.scrollHeight;
}
function answerHtml(t) {
  const re = /【(.+?)】/g; const parts = []; let m, last = 0, idx = null;
  while ((m = re.exec(t))) { if (idx !== null) parts.push([idx, t.slice(last, m.index)]); else if (m.index > 0 && t.slice(0, m.index).trim()) parts.push(['', t.slice(0, m.index)]); idx = m[1]; last = re.lastIndex; }
  if (idx === null) return `<div>${md(t)}</div>`;
  parts.push([idx, t.slice(last)]);
  const order = ['依据', '操作步骤', '风险提醒', '下一步建议'];
  return parts.map(([h, b]) => { const s = order.indexOf(h); return `<div class="sec s${s < 0 ? 4 : s}">${h ? `<h4>${esc(h)}</h4>` : ''}${md(b.trim())}</div>`; }).join('');
}
R['wen/chat'] = rt => {
  chrome(rt, '云问 · AI顾问', true);
  view(`<div class="chatwrap"><div class="msgs" id="msgs"></div>
    <div class="inputbar"><input id="q" placeholder="请输入您的问题…" autocomplete="off"><button data-a="send">➤</button></div></div>`, true);
  renderChat();
  const q = rt.q.get('q');
  if (q && !S.chat.length) sendQ(q);
  $('#q').addEventListener('keydown', e => { if (e.key === 'Enter') sendQ(); });
};
async function sendQ(text) {
  const inp = $('#q'); const q = (text || (inp && inp.value) || '').trim();
  if (!q || S.busy) return; if (inp) inp.value = '';
  S.chat.push({ role: 'user', text: q }); S.busy = true; renderChat();
  try {
    const d = await api('/api/wen', { question: q, conversation_id: S.conv || null, history: S.chat.slice(-7, -1).map(m => ({ role: m.role, text: m.text })) });
    if (d.conversation_id) S.conv = d.conversation_id;
    S.chat.push({ role: 'assistant', text: d.answer || '（无回复）', sugg: d.suggestions || [] }); logAct('wen', '云问 · ' + q.slice(0, 18));
    pushMsg({ agent: 'wen', kind: 'wen', title: '云问已回复', summary: q.slice(0, 30), payload: { q, a: d.answer || '' } }, S.cur === 'wen/chat');
  } catch (e) { S.chat.push({ role: 'assistant', text: '【风险提醒】' + e.message }); }
  S.busy = false; renderChat();
}

/* ---------- 云创 ---------- */
R.chuang = rt => {
  chrome(rt, '云创 · 内容生成', true);
  const hist = LS.get('chuang_hist', []);
  view(`<div class="hero"><h1>✨ 云创 AI 内容创作</h1><p>填写商品信息，快速生成多平台营销内容</p>
      <button class="btn-w" data-a="newc">开始创作 ›</button></div>
    <h2>快速创作</h2><div class="grid3" style="margin-top:10px">
      ${[['📕', '小红书', '小红书文案'], ['💬', '朋友圈', '朋友圈文案'], ['🎬', '抖音短视频', '抖音短视频脚本'], ['🎙️', '直播间口播', '直播口播'], ['🏷️', '商品卖点', '商品卖点']]
      .map(t => `<div class="tile" data-a="newc" data-t="${t[2]}"><b>${t[0]}</b>${t[1]}</div>`).join('')}
      <div class="tile off" data-a="soon"><b>🖼️</b>图片</div></div>
    <h2>案例模板</h2><div class="mut" style="margin-bottom:10px">一键填充，快速上手</div>
    <div class="grid3">${TPL.map((t, i) => `<div class="tile" data-a="tpl" data-i="${i}"><b>${t[0]}</b>${t[1]}</div>`).join('')}</div>
    <h2>历史记录</h2>${hist.length ? hist.map((h, i) => `<div class="cust" data-a="openhist" data-i="${i}"><div class="av" style="background:#E8F0FF;color:#0066FF">📄</div><div style="min-width:0"><div class="t">${esc(h.title)}</div><div class="l">${esc(h.type)} · ${ago(h.t)}</div></div></div>`).join('') : '<div class="empty">暂无历史记录</div>'}`);
};
R['chuang/new'] = rt => {
  chrome(rt, '生成内容', true);
  const f = S.form; f.type = f.type || '小红书文案'; f.style = f.style || '温暖亲切';
  view(`<label class="f" style="margin-top:0">内容类型</label><div class="chips" data-g="type">${TYPES.map(t => `<span class="chip ${f.type === t ? 'on' : ''}" data-a="pick" data-g="type" data-v="${t}">${t}</span>`).join('')}</div>
    <label class="f">商品名称 *</label><input class="in" id="f_product" placeholder="如：纯银戒指" value="${esc(f.product || '')}">
    <label class="f">核心卖点</label><input class="in" id="f_points" placeholder="如：纯银材质、简约设计" value="${esc(f.points || '')}">
    <label class="f">目标人群</label><input class="in" id="f_audience" placeholder="如：25-35岁上班族" value="${esc(f.audience || '')}">
    <label class="f">文案风格</label><div class="chips">${STYLES.map(t => `<span class="chip ${f.style === t ? 'on' : ''}" data-a="pick" data-g="style" data-v="${t}">${t}</span>`).join('')}</div>
    <button class="btn" id="genbtn" data-a="gen">✨ 立即生成</button><div id="genst"></div>`);
};
function readForm() { const f = S.form; ['product', 'points', 'audience'].forEach(k => { const el = $('#f_' + k); if (el) f[k] = el.value.trim(); }); }
async function generate() {
  readForm(); const f = S.form;
  if (!f.product) return toast('请填写商品名称');
  $('#genbtn').disabled = true; $('#genst').innerHTML = loading('云创正在生成，请稍候…');
  try {
    const d = await api('/api/chuang', { platform: f.type, product: f.product, selling_points: f.points || '', audience: f.audience || '', style: f.style || '' });
    S.result = { ...d, type: f.type, product: f.product, t: Date.now() }; logAct('chuang', '云创 · 生成了「' + (d.title || f.product) + '」');
    const onNew = S.cur === 'chuang/new', onRes = S.cur === 'chuang/result';
    pushMsg({ agent: 'chuang', kind: 'chuang', title: '云创已生成：' + (d.title || f.product), summary: f.type + ' · ' + f.product, payload: { result: S.result } }, onNew || onRes);
    if (onNew) go('#/chuang/result'); else if (onRes) render();
  } catch (e) { const st = $('#genst'), gb = $('#genbtn'); if (st) st.innerHTML = `<div class="err">${esc(e.message)}</div>`; if (gb) gb.disabled = false; toast(e.message); }
}
R['chuang/result'] = rt => {
  chrome(rt, S.result ? '生成结果' : '生成结果', true);
  const r = S.result; if (!r) { go('#/chuang'); return; }
  view(`<div class="card"><h3 style="font-size:17px">${esc(r.title)}</h3>
      ${r.digest ? `<div class="mut" style="margin-bottom:8px">${esc(r.digest)}</div>` : ''}
      <div style="font-size:14px;line-height:1.75">${md(r.body)}</div>
      <div class="chips" style="margin-top:10px">${(r.hashtags || []).map(h => `<span class="chip">#${esc(h)}</span>`).join('')}</div></div>
    <div class="row"><button class="btn line" id="genbtn" data-a="gen">↻ 重新生成</button><button class="btn line" data-a="copyres">复制</button></div>
    <div class="row"><button class="btn gray" data-a="saveres">保存到历史</button><button class="btn" data-a="queue">加入发布队列</button></div><div id="genst"></div>`);
};

/* ---------- 云搭 ---------- */
R.da = rt => {
  chrome(rt, '云搭 · AI商品搭配', true);
  const f = S.daf = S.daf || { scene: '旅行', style: '简约', budget: '¥500-1000' };
  view(`<div class="hero"><h1>🛍️ 场景化商品搭配</h1><p>选场景 · 填需求 · 获方案</p></div>
    ${S.health.da_bots > 1 ? `<div class="chips" style="margin-bottom:12px">${(S.health.da_labels || ['方案一', '方案二']).map((l, i) => `<span class="chip ${(S.dabot || '1') === String(i + 1) ? 'on' : ''}" data-a="dbot" data-v="${i + 1}">${esc(l)}</span>`).join('')}</div>` : ''}<h3>选择使用场景</h3><div class="grid3">${SCENES.map(s => `<div class="tile ${f.scene === s[0] ? 'on' : ''}" data-a="scene" data-v="${s[0]}"><b>${s[2]}</b>${s[0]}<div class="mut" style="font-size:10px">${s[1]}</div></div>`).join('')}</div>
    <h3 style="margin-top:18px">填写搭配需求</h3>
    <label class="f" style="margin-top:0">商品类型 *</label><input class="in" id="d_cat" placeholder="如：女装、数码配件、家居用品" value="${esc(f.cat || '')}">
    <label class="f">预算范围</label><select class="in" id="d_budget">${['¥200-500', '¥500-1000', '¥1000-2000', '¥2000以上', '不限'].map(b => `<option ${f.budget === b ? 'selected' : ''}>${b}</option>`).join('')}</select>
    <label class="f">目标人群</label><input class="in" id="d_aud" placeholder="如：学生党、宝妈、职场新人" value="${esc(f.aud || '')}">
    <label class="f">风格偏好</label><div class="chips">${PSTYLES.map(s => `<span class="chip ${f.style === s ? 'on' : ''}" data-a="dstyle" data-v="${s}">${s}</span>`).join('')}</div>
    <button class="btn" id="dbtn" data-a="dgen">✨ 生成搭配方案</button><div id="dst"></div><div id="plans">${S.plans ? plansHtml(S.plans) : ''}</div>`);
};
const PCOL = { '省钱': 'linear-gradient(135deg,#10B981,#059669)', '精品': 'linear-gradient(135deg,#8B5CF6,#6D28D9)', '热销': 'linear-gradient(135deg,#FF7A45,#F5222D)' };
function plansHtml(d) {
  if (d.raw && !(d.plans || []).length) return `<div class="card" style="margin-top:16px"><h3>✨ 搭配方案</h3>${(d.images || []).map(u => `<img src="${esc(u)}" style="width:100%;border-radius:12px;margin:8px 0">`).join('')}${md(d.raw)}<button class="btn sm gray" data-a="copyraw">复制</button></div><button class="btn line" data-a="dgen">↻ 重新生成方案</button>`;
  const ps = d.plans || [];
  return `<div class="card" style="background:#f3efff;margin-top:16px">✨ <b>方案生成完毕</b><div class="mut">已为你生成 ${ps.length} 套搭配方案，点击卡片查看详情</div></div>` +
    ps.map((p, i) => `<div class="plan"><div class="ph" style="background:${PCOL[p.tag] || PCOL['精品']}"><span>${esc(p.tag || '')}　${esc(p.name || '')}</span><span class="pr">${esc(p.price_range || '')}</span></div>
      <div class="pb"><div class="items">${(p.items || []).map(it => `<div class="it"><b>${esc(it.name)}</b><span>${esc(it.price_range || '')}</span><div class="mut" style="font-size:11px">${esc(it.role || '')}</div></div>`).join('')}</div>
      <div class="mut">📍 ${esc(p.suitable || '')}</div><div style="font-size:13px;margin:6px 0">${esc(p.highlights || '')}</div>
      <button class="btn sm line" data-a="script" data-i="${i}">查看导购话术</button> <button class="btn sm gray" data-a="copyscript" data-i="${i}">复制话术</button>${S.health.da_image ? ` <button class="btn sm" data-a="dimg" data-i="${i}">🖼️ 生成使用效果图</button>` : ''}
      <div class="script" id="sc${i}">${fmt(p.sales_script || '')}</div></div></div>`).join('') +
    `<button class="btn line" data-a="dgen">↻ 重新生成方案</button>`;
}
async function genPlans() {
  const f = S.daf; f.cat = $('#d_cat').value.trim(); f.budget = $('#d_budget').value; f.aud = $('#d_aud').value.trim();
  if (!f.cat) return toast('请填写商品类型');
  $('#dbtn').disabled = true; $('#dst').innerHTML = loading('云搭正在生成方案…');
  try {
    S.plans = await api('/api/da', { bot: S.dabot || '1', scene: f.scene, category: f.cat, budget: f.budget, audience: f.aud, style: f.style });
    logAct('da', '云搭 · ' + f.scene + '场景搭配');
    const here = S.cur === 'da';
    pushMsg({ agent: 'da', kind: 'da', title: '云搭方案已生成', summary: f.scene + ' · ' + f.cat, payload: { plans: S.plans, f: { ...f }, bot: S.dabot || '1' } }, here);
    if (here && $('#plans')) { $('#dst').innerHTML = ''; $('#plans').innerHTML = plansHtml(S.plans); $('#plans').scrollIntoView({ behavior: 'smooth' }); }
  } catch (e) { const st = $('#dst'); if (st) st.innerHTML = `<div class="err">${esc(e.message)}</div>`; toast(e.message); }
  const bt = $('#dbtn'); if (bt) bt.disabled = false;
}

/* ---------- 云服 ---------- */
function custs() { return S.cust || (S.cust = JSON.parse(JSON.stringify(CUST))); }
R.fu = rt => {
  chrome(rt, '云服 · 智能客服', true);
  const cs = custs();
  view(`<div class="hero" style="background:linear-gradient(135deg,#4FACFE,#8B5CF6)"><h1>🎧 云服工作台</h1><p>智能客服 · 实时响应</p></div>
    <div class="stat4"><div><b style="color:#0066FF">47</b><span>今日咨询</span></div><div><b style="color:#8B5CF6">23秒</b><span>均响应时长</span></div><div><b style="color:#10B981">${cs.filter(c => c.st === '已解决').length + 37}</b><span>已解决</span></div><div><b style="color:#F59E0B">96.8%</b><span>满意度</span></div></div>
    ${S.health.fu_shops > 1 ? `<div class="chips" style="margin-bottom:10px"><span class="chip ${S.shop !== '2' ? 'on' : ''}" data-a="shop" data-v="1">${esc((S.health.fu_labels || [])[0] || '店铺一')}</span><span class="chip ${S.shop === '2' ? 'on' : ''}" data-a="shop" data-v="2">${esc((S.health.fu_labels || [])[1] || '店铺二')}</span></div>` : ''}
    <div class="mut" style="margin:-4px 0 8px">示例数据 · 以下为模拟客户会话</div>
    <h3>客户会话 <span class="tg b">${cs.filter(c => c.st !== '已解决').length}个进行中</span></h3>
    ${cs.map(c => `<div class="cust" data-a="go" data-h="#/fu/chat?id=${c.id}"><div class="av" style="background:${c.bg};color:${c.c}">${esc(c.name[0])}${c.unread ? `<em>${c.unread}</em>` : ''}</div>
      <div style="min-width:0"><div class="t">${esc(c.name)}<span class="tg ${c.tc}">${esc(c.tag)}</span>${c.st ? `<span class="tg ${c.st === '已解决' ? 'g' : c.st === '紧急' ? 'r' : 'o'}">${esc(c.st)}</span>` : ''}</div><div class="l">${esc(c.msgs[c.msgs.length - 1][1])}</div></div><div class="tm">${c.time}</div></div>`).join('')}`);
};
R['fu/chat'] = rt => {
  const c = custs().find(x => x.id === +rt.q.get('id')); if (!c) { go('#/fu'); return; }
  chrome(rt, c.name + (c.tag ? ' · ' + c.tag : ''), true); c.unread = 0;
  view(`<div class="chatwrap"><div class="msgs" id="cmsgs"></div><div class="aibox" id="aibox"></div></div>`, true);
  drawCust(c); loadReplies(c);
};
function drawCust(c) {
  const m = $('#cmsgs'); if (!m) return;
  m.innerHTML = c.msgs.map(x => `<div class="bub ${x[0] === 'a' ? 'u' : 'c'}">${fmt(x[1])}</div>`).join('') + (c.st === '已解决' ? '<div class="empty">✓ 已标记为已解决</div>' : '');
  m.scrollTop = m.scrollHeight;
}
async function loadReplies(c, force) {
  const box = $('#aibox'); if (!box) return;
  if (S.custReplies[c.id] && !force) return drawReplies(c);
  box.innerHTML = `<div class="hd">✨ AI 推荐回复</div>${loading('正在分析客户问题…')}`;
  try {
    S.custReplies[c.id] = await api('/api/fu/replies', { shop: S.shop || '1', conversation: c.msgs.map(x => ({ role: x[0] === 'a' ? '客服' : '客户', text: x[1] })) });
    S.custReplies[c.id].sel = 0; logAct('fu', '云服 · 处理了「' + c.name + '」的咨询');
    const r0 = (S.custReplies[c.id].replies || [])[0];
    pushMsg({ agent: 'fu', kind: 'fu', title: '云服已生成回复：' + c.name, summary: c.tag + ' · ' + (r0 ? r0.text : '').slice(0, 24), payload: { id: c.id } }, S.cur === 'fu/chat');
  } catch (e) { box.innerHTML = `<div class="hd">✨ AI 推荐回复</div><div class="err">${esc(e.message)}</div>`; return; }
  drawReplies(c);
}
function drawReplies(c) {
  const box = $('#aibox'); const d = S.custReplies[c.id]; if (!box || !d) return; const rs = d.replies || []; const cur = rs[d.sel || 0];
  box.innerHTML = `<div class="hd">✨ AI 推荐回复 · ${rs.length}条 ${d.urgent ? '<span class="tg r" style="margin-left:auto">紧急</span>' : ''}</div>
    <div class="chips">${rs.map((r, i) => `<span class="chip ${i === (d.sel || 0) ? 'on' : ''}" data-a="rsel" data-id="${c.id}" data-i="${i}">${esc(r.tone)}</span>`).join('')}</div>
    <div class="rp">${fmt(cur ? cur.text : '')}</div>
    <div class="row"><button class="btn sm gray" data-a="rcopy" data-id="${c.id}">复制</button><button class="btn sm" data-a="rsend" data-id="${c.id}">一键发送</button></div>
    <div class="row" style="margin-top:8px"><button class="btn sm line" data-a="human">转人工</button><button class="btn sm gray" data-a="resolve" data-id="${c.id}">标记已解决</button><button class="btn sm gray" data-a="rreload" data-id="${c.id}">↻ 重新生成</button></div>`;
}

/* ---------- 云析 ---------- */
function xiData(sum, r) {
  if (sum && sum.has_data && sum.metrics.length) {
    return { real: true, note: `真实数据 · ${sum.date_range[0]} 至 ${sum.date_range[1]}` + (sum.days_covered < sum.days ? `（所选周期内仅有 ${sum.days_covered} 天数据）` : ''),
      metrics: sum.metrics.map(m => ({ label: m.label, display: m.display, d: fmtDelta(m), neg: m.delta < 0 })),
      pts: sum.series.map(x => x.gmv).filter(v => v !== null && v !== undefined), series: sum.series };
  }
  return { real: false, metrics: metricsFor(r).map(m => ({ label: m[0], display: m[1], d: m[2], neg: false })), pts: RANGES[r].pts, series: [] };
}
R.xi = async rt => {
  chrome(rt, '云析 · 数据分析', true);
  const r = S.range = S.range || '近7日'; S.xsum = S.xsum || {};
  const paint = sm => {
    const x = S.xcur = xiData(sm, r);
    view(`<div class="chips" style="margin-bottom:12px">${Object.keys(RANGES).map(k => `<span class="chip ${k === r ? 'on' : ''}" data-a="range" data-v="${k}">${k}</span>`).join('')}</div>
    <h3>核心指标 ${x.real ? '<span class="mockchip" style="background:#e6f7f0;color:#0b8a5f">真实数据</span>' : '<span class="mockchip">示例数据</span>'}</h3>
    ${x.real ? `<div class="mut" style="margin-bottom:8px">${esc(x.note)}</div>` : `<div class="warn">当前为示例数据。导入你的店铺数据后，这里会显示真实指标。<span data-a="go" data-h="#/data" style="color:#0066FF;text-decoration:underline">去导入 ›</span></div>`}
    <div class="grid2">${x.metrics.map(m => `<div class="metric">${m.d ? `<span class="d ${m.neg ? 'dn' : ''}">${m.d}</span>` : ''}<span>${esc(m.label)}</span><b>${esc(m.display)}</b></div>`).join('')}</div>
    <h3 style="margin-top:18px">${r}销售趋势</h3><div class="card">${x.pts.length >= 2 ? chart(x.pts) : '<div class="empty">数据点不足，无法绘制趋势</div>'}</div>
    <button class="btn" id="xbtn" data-a="diag">🧠 生成 AI 诊断报告</button><div id="xst"></div><div id="diag">${S.diag && S.diag.r === r ? diagHtml(S.diag.d) : ''}</div>`);
  };
  if (S.xsum[r]) paint(S.xsum[r]); else view(loading('加载数据…'));
  try { const sm = await api('/api/data/summary?days=' + RANGES[r].days); S.xsum[r] = sm; if (S.cur === 'xi' && S.range === r) paint(sm); }
  catch (e) { if (!S.xsum[r] && S.cur === 'xi') paint(null); }
};
function chart(p) {
  const W = 360, H = 120, mx = Math.max(...p), mn = Math.min(...p) * 0.9; const x = i => 10 + i * (W - 20) / (p.length - 1), y = v => H - 10 - (v - mn) / (mx - mn) * (H - 30);
  const d = p.map((v, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1)).join(' ');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><defs><linearGradient id="ga" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0066FF" stop-opacity=".25"/><stop offset="1" stop-color="#0066FF" stop-opacity="0"/></linearGradient></defs>
    <path d="${d} L${x(p.length - 1)} ${H} L${x(0)} ${H}Z" fill="url(#ga)"/><path d="${d}" fill="none" stroke="#0066FF" stroke-width="2.5" stroke-linejoin="round"/>${p.map((v, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3" fill="#fff" stroke="#0066FF" stroke-width="2"/>`).join('')}</svg>`;
}
function diagHtml(d) {
  if (d.raw && !d.conclusion) return `<div class="diag"><h3>🧠 AI 诊断报告</h3><div class="sec">${md(d.raw)}</div></div>`;
  const li = a => (a || []).map(x => `<div>• ${esc(x)}</div>`).join('');
  return `<div class="diag"><h3>🧠 AI 诊断报告 <span class="mut" style="color:#aab">基于${esc(S.diag.r)}数据自动生成</span></h3>
    <div class="sec"><h4>💡 核心结论</h4>${esc(d.conclusion || '')}</div>
    <div class="sec"><h4>📊 数据支撑</h4>${li(d.evidence)}</div>
    <div class="sec pb"><h4>⚠️ 问题诊断</h4>${li(d.problems)}</div>
    <div class="sec sg"><h4>🚀 优化建议</h4>${(d.suggestions || []).map(s => `<div>• [${esc(s.priority || '')}] ${esc(s.action || '')}${s.expected ? '（' + esc(s.expected) + '）' : ''}</div>`).join('')}</div>
    <button class="btn sm gray" data-a="copydiag">复制报告</button></div>`;
}
async function diag() {
  const r = S.range, x = S.xcur || xiData(null, r), metrics = {};
  x.metrics.forEach(m => { metrics[m.label] = m.display + (m.d ? '（较上一周期' + m.d + '）' : ''); });
  if (x.real && x.series.length) metrics['每日销售额'] = x.series.slice(-14).map(p => p.date.slice(5) + ':' + (p.gmv ?? '—')).join('；');
  $('#xbtn').disabled = true; $('#xst').innerHTML = loading('云析正在分析数据…');
  try {
    const d = await api('/api/xi/report', { range: r, metrics }); S.diag = { r, d }; logAct('xi', '云析 · 生成了' + r + '诊断报告');
    const here = S.cur === 'xi';
    pushMsg({ agent: 'xi', kind: 'xi', title: '云析诊断报告已生成', summary: r + (x.real ? ' · 真实数据' : ' · 示例数据'), payload: { range: r, d } }, here);
    if (here && $('#diag')) { $('#xst').innerHTML = ''; $('#diag').innerHTML = diagHtml(d); }
  } catch (e) { const st = $('#xst'); if (st) st.innerHTML = `<div class="err">${esc(e.message)}</div>`; toast(e.message); }
  const bt = $('#xbtn'); if (bt) bt.disabled = false;
}

/* ---------- 工作台 / 消息 / 我的 ---------- */
R.work = async rt => {
  chrome(rt, '工作台');
  const c = LS.get('cnt', { all: 0, chuang: 0, wen: 0 }), msgs = MSGS.load(), hasTk = !!LS.get('admin_token', '');
  const ag = k => agent(k) || { name: '系统', bg: '#EDE7FF', c: '#8B5CF6' };
  view(`<div class="hero"><h1>你好，智研用户</h1><p>今日已完成 ${c.all} 次 AI 调用 · 未读消息 ${unreadCount()} 条</p></div>
    <h3>待办</h3>
    <div class="grid2">${hasTk ? `<div class="metric" data-a="go" data-h="#/publish" style="cursor:pointer"><span>待审核内容</span><b id="td1">…</b></div><div class="metric" data-a="go" data-h="#/publish" style="cursor:pointer"><span>待执行发布计划</span><b id="td2">…</b></div>`
      : `<div class="card" style="grid-column:1/3;cursor:pointer" data-a="go" data-h="#/publish">设置管理口令后，这里显示待审核内容和待执行计划 ›</div>`}</div>
    <h3 style="margin-top:14px">快捷入口</h3><div class="grid3">${AG.map(a => `<div class="tile" data-a="go" data-h="#/${a.k}"><b>${a.ic}</b>${a.name}</div>`).join('')}</div>
    <div class="card" data-a="go" data-h="#/publish" style="cursor:pointer;display:flex;align-items:center;gap:12px;margin-top:14px"><div class="ico" style="background:var(--g1)">🤖</div><div><b>自动发布</b><div class="mut">每日选题 → 生成 → 审核 → 公众号 / 小红书 / 抖音</div></div><div class="ch" style="margin-left:auto;color:#c3c7d6">›</div></div>
    <h3>近期任务</h3>${msgs.length ? msgs.slice(0, 6).map(m => { const a = ag(m.agent); return `<div class="cust" data-a="openmsg" data-id="${m.id}"><div class="av" style="background:${a.bg};color:${a.c}">${esc(a.name)}${m.read ? '' : '<em class="udot"></em>'}</div><div style="min-width:0;flex:1"><div class="t">${esc(m.title)}</div><div class="l">${esc(m.summary || '')}</div></div><div class="tm">${ago(m.t)}</div></div>`; }).join('') : '<div class="empty">还没有任务，去试试五大助手吧</div>'}
    <h3 style="margin-top:16px">本次使用统计</h3><div class="stat4" style="grid-template-columns:repeat(3,1fr)"><div><b style="color:#0066FF">${c.all}</b><span>调用次数</span></div><div><b style="color:#8B5CF6">${c.chuang}</b><span>生成内容</span></div><div><b style="color:#10B981">${c.wen}</b><span>咨询问答</span></div></div>`);
  if (hasTk) {
    try {
      const ts = await api('/api/publish/tasks', null, { admin: true }), ss = await api('/api/publish/schedules', null, { admin: true });
      if ($('#td1')) { $('#td1').textContent = ts.filter(t => t.status === 'pending_review').length; $('#td2').textContent = ss.filter(x => x.status === 'scheduled').length; }
    } catch (e) { if ($('#td1')) { $('#td1').textContent = '—'; $('#td2').textContent = '—'; } }
  }
};
R.msg = rt => {
  chrome(rt, '消息');
  const list = MSGS.load(), ag = k => agent(k) || { name: '系统', bg: '#EDE7FF', c: '#8B5CF6' };
  view(`<div class="row" style="margin-bottom:12px"><button class="btn sm gray" data-a="readall">全部已读</button><button class="btn sm gray" data-a="clearmsg">清空历史</button></div>` +
    (list.length ? list.map(m => { const a = ag(m.agent); return `<div class="cust" data-a="openmsg" data-id="${m.id}"><div class="av" style="background:${a.bg};color:${a.c}">${esc(a.name)}${m.read ? '' : '<em class="udot"></em>'}</div><div style="min-width:0;flex:1"><div class="t" style="${m.read ? 'font-weight:500;color:#555' : ''}">${esc(m.title)}</div><div class="l">${esc(m.summary || '')}</div></div><div class="tm">${ago(m.t)}</div></div>`; }).join('')
      : '<div class="empty">还没有消息<br>智能体生成内容后，这里会出现提醒和历史记录</div>'));
};
R.me = rt => {
  chrome(rt, '我的');
  view(`<div class="hero" style="display:flex;gap:12px;align-items:center"><div class="ico" style="background:rgba(255,255,255,.25)">👤</div><div><h1 style="margin:0">智研用户</h1><p>账号：示例账号</p></div></div>
    <div class="menu">${[['📦', '我的订单'], ['📊', '使用统计'], ['❓', '帮助中心'], ['💬', '意见反馈'], ['⚙️', '设置']].map(m => `<a data-a="soon"><b>${m[0]}</b>${m[1]}<span>›</span></a>`).join('')}
      <a data-a="go" data-h="#/data"><b>🗂️</b>数据管理（导入店铺数据）<span>›</span></a>
      <a data-a="go" data-h="#/publish"><b>🤖</b>自动发布管理<span>›</span></a>
      <a data-a="go" data-h="#/diagnose"><b>🩺</b>系统自检<span>›</span></a></div>`);
};

/* ---------- 数据管理 ---------- */
const tokenBox = `<div class="card"><h3>请先输入管理口令</h3><div class="mut">即后端 .env 里的 ADMIN_TOKEN，仅保存在本浏览器</div><input class="in" id="tk" type="password" placeholder="管理口令" style="margin-top:10px"><button class="btn" data-a="savetk2">确定</button></div>`;
R.data = async rt => {
  chrome(rt, '数据管理', true);
  let sm = null; try { sm = await api('/api/data/summary?days=7'); S.sum = sm; S.xsum = {}; } catch (e) { /* ignore */ }
  const tk = LS.get('admin_token', ''); S.imode = S.imode || 'merge';
  view(`<div class="card"><h3>当前数据</h3>${sm && sm.has_data ? `已导入 <b>${sm.rows}</b> 天数据：${sm.date_range[0]} 至 ${sm.date_range[1]}<div class="mut" style="margin-top:4px">首页和云析正在使用这些数据</div>` : '尚未导入。首页和云析目前显示的是示例数据。'}</div>
    ${tk ? '' : tokenBox}
    <div class="card"><h3>导入每日经营数据（CSV）</h3>
      <div class="mut" style="line-height:1.6">表头需包含：<b>日期、访客、订单、销售额</b>，可选：广告花费、复购订单。Excel 请先“另存为 CSV”。同一天重复导入会更新。</div>
      <div class="row" style="margin:10px 0"><button class="btn sm gray" data-a="tplcsv">⬇ 下载模板</button><label class="btn sm line" style="text-align:center;cursor:pointer">📁 选择文件<input type="file" id="csvfile" accept=".csv,.txt,text/csv" style="display:none"></label></div>
      <textarea class="in" id="csvtext" rows="6" placeholder="也可以把 CSV 内容直接粘贴到这里"></textarea>
      <div class="chips" style="margin-top:10px"><span class="chip ${S.imode === 'merge' ? 'on' : ''}" data-a="imode" data-v="merge">合并更新</span><span class="chip ${S.imode === 'replace' ? 'on' : ''}" data-a="imode" data-v="replace">覆盖全部</span></div>
      <button class="btn" data-a="doimport">导入</button><div id="imsg">${S.iresult || ''}</div></div>
    ${sm && sm.has_data ? '<button class="btn gray" data-a="cleardata">清空已导入的数据</button>' : ''}`);
  const f = $('#csvfile'); if (f) f.addEventListener('change', async () => {
    const file = f.files[0]; if (!file) return; const buf = await file.arrayBuffer(); let text = new TextDecoder('utf-8').decode(buf);
    if (!/日期|date/i.test(text.split('\n')[0] || '')) { try { text = new TextDecoder('gbk').decode(buf); } catch (e) { /* ignore */ } }
    $('#csvtext').value = text; toast('已读取：' + file.name);
  });
};
function csvTemplate() {
  const rows = ['日期,访客,订单,销售额,广告花费,复购订单']; const base = new Date();
  for (let i = 6; i >= 0; i--) { const d = new Date(base); d.setDate(d.getDate() - i); const v = 800 + Math.round(Math.random() * 400), o = Math.round(v * 0.04), g = o * 100;
    rows.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')},${v},${o},${g},${Math.round(g * 0.12)},${Math.round(o * 0.3)}`); }
  return '\ufeff' + rows.join('\n');
}

/* ---------- 系统自检 ---------- */
const BE = { coze: 'Coze', llm: '备用模型', mock: '演示模式' };
function paintDiag(d) {
  const box = $('#dgres'); if (!box) return;
  const fm = a => a.format === 'json' ? '<span class="tg g">结构化 JSON ✓</span>' : a.format === 'text' ? '<span class="tg o">纯文本（页面按文本展示）</span>' : a.format === 'mock' ? '<span class="tg b">演示</span>' : '';
  const textBots = d.agents.filter(a => a.ok && a.format === 'text' && a.key !== 'wen').map(a => a.name);
  box.innerHTML = `<h3 style="margin-top:14px">配置检查</h3>` + d.checks.map(c => `<div class="card" style="padding:10px 14px;margin-bottom:8px"><b>${c.ok ? '✅' : '⚠️'} ${esc(c.name)}</b><div class="mut">${esc(c.detail)}</div></div>`).join('') +
    `<h3 style="margin-top:14px">智能体测试</h3>` + d.agents.map(a => `<div class="card" style="padding:12px 14px;margin-bottom:8px"><b>${a.ok ? '✅' : '❌'} ${esc(a.name)}</b> <span class="tg b">${BE[a.backend] || a.backend}</span> ${fm(a)} <span class="mut">${a.ms} ms</span>
      ${a.sample ? `<div class="mut" style="margin-top:4px;word-break:break-all">${esc(a.sample)}</div>` : ''}${a.error ? `<div class="err">${esc(a.error)}</div>` : ''}</div>`).join('') +
    (textBots.length ? `<div class="warn">${esc(textBots.join('、'))} 的 Bot 没有按 JSON 输出，页面会直接显示文本，功能可用。想让页面展示更规整，可在 Bot 提示词中要求按 JSON 输出，或把对应功能加入 COZE_RAW_AGENTS 让 Bot 完全按自己的方式回答。</div>` : '') +
    `<div class="mut" style="margin-top:8px">可以把本页截图发给开发者，用来定位问题。</div>`;
}
R.diagnose = rt => {
  chrome(rt, '系统自检', true);
  view(`<div class="card"><div class="mut" style="line-height:1.6">依次测试五个智能体并检查配置，约需 10–60 秒（会真实调用 Coze）。</div>
    <button class="btn" data-a="rundiag" data-w="0">开始检测</button><button class="btn line" data-a="rundiag" data-w="1">检测并测试公众号连接</button></div>
    ${LS.get('admin_token', '') ? '' : tokenBox}<div id="dgres"></div>`);
  if (S.diagres) paintDiag(S.diagres);
};

/* ---------- 自动发布管理 ---------- */
const STN = { pending_review: '待审核', approved: '已通过', drafted: '已进草稿箱', published: '已发布', failed: '失败', rejected: '已驳回' };
R.publish = async rt => {
  chrome(rt, '自动发布管理', true);
  if (!LS.get('admin_token', '')) {
    view(`<div class="card"><h3>请输入管理口令</h3><div class="mut">即后端 .env 里的 ADMIN_TOKEN，仅保存在本浏览器</div><input class="in" id="tk" type="password" placeholder="管理口令" style="margin-top:10px"><button class="btn" data-a="savetk">确定</button></div>`); return;
  }
  view(`<div class="row"><button class="btn sm" data-a="plan">🤖 立即生成一篇</button><button class="btn sm gray" data-a="reload">刷新</button><button class="btn sm gray" data-a="cleartk">退出口令</button></div><div id="pst"></div><div id="tasks" style="margin-top:12px">${loading('加载中…')}</div>`);
  loadTasks();
};
async function loadTasks() {
  const box = $('#tasks'); if (!box) return;
  try {
    const ts = await api('/api/publish/tasks', null, { admin: true });
    S.tasks = ts;
    S.scheds = {};
    try { (await api('/api/publish/schedules', null, { admin: true })).forEach(x => { (S.scheds[x.task_id] = S.scheds[x.task_id] || []).push(x); }); } catch (e) { /* ignore */ }
    box.innerHTML = ts.length ? ts.map(t => `<div class="task"><div style="display:flex;justify-content:space-between;gap:8px"><b style="font-size:15px">#${t.id} ${esc(t.title)}</b><span class="st ${t.status}">${STN[t.status] || t.status}</span></div>
      ${t.issues && t.issues.length ? `<div class="warn">⚠️ 合规风险：${t.issues.map(i => esc(i.word)).join('、')}</div>` : ''}
      <div class="bd">${esc(t.body)}</div>${t.error ? `<div class="err">${esc(t.error)}</div>` : ''}
      ${schedHtml(t.id)}<div class="row" style="flex-wrap:wrap">${taskBtns(t)}</div></div>`).join('') : '<div class="empty">暂无任务，点「立即生成一篇」试试</div>';
  } catch (e) { box.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}
const SCN = { scheduled: '待执行', running: '执行中', done: '已完成', failed: '失败', cancelled: '已取消' };
const PNAME = { wechat: '公众号', xiaohongshu: '小红书', douyin: '抖音' };
const fmtT = ts => new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const adaptedText = c => [c.title || '', c.body || '', (c.hashtags || []).map(h => '#' + h).join(' ')].filter(Boolean).join('\n\n');
function schedHtml(tid) {
  const ss = (S.scheds && S.scheds[tid]) || []; if (!ss.length) return '';
  return `<div style="margin:8px 0">${ss.map(x => {
    const r = x.result || {}, c = r.content;
    return `<div class="warn" style="background:#f3f6ff;color:#334">📅 ${esc(PNAME[x.platform] || x.platform)} · ${fmtT(x.run_at)} · <b>${SCN[x.status] || x.status}</b>
      ${r.message ? `<div>${esc(r.message)}</div>` : ''}${x.error ? `<div class="err">${esc(x.error)}</div>` : ''}
      ${c ? `<div class="bd" style="max-height:none;white-space:pre-wrap">${esc(adaptedText(c))}</div><button class="btn sm gray" data-a="scopy" data-id="${x.id}">复制内容</button>` : ''}
      ${x.status === 'scheduled' ? ` <button class="btn sm line" data-a="scancel" data-id="${x.id}">取消</button>` : ''}</div>`;
  }).join('')}</div>`;
}
function updHint() {
  const el = $('#s_plat'), h = $('#s_hint'); if (!el || !h) return;
  h.innerHTML = el.value.split(',').map(k => { const p = (S.pinfo || []).find(x => x.key === k); return `• ${esc(PNAME[k])}：${esc(p ? p.mode : '')}`; }).join('<br>');
}
function taskBtns(t) {
  const b = (a, l, c) => `<button class="btn sm ${c || ''}" data-a="${a}" data-id="${t.id}">${l}</button>`;
  if (t.status === 'pending_review' || t.status === 'failed') return b('tedit', '编辑', 'gray') + b('tappr', '通过') + b('trej', '驳回', 'line');
  if (t.status === 'approved') return b('tpub', '存入公众号草稿箱', 'gray') + b('tpubd', '🚀 直接发布到公众号') + b('tsched', '📅 发布计划', 'line');
  if (t.status === 'drafted') return b('tsubmit', '🚀 提交发布') + b('tsched', '📅 发布计划', 'line') + '<div class="mut" style="flex-basis:100%">公众号：已在草稿箱。可点“提交发布”，或到手机上确认发布</div>';
  if (t.status === 'published') return b('tcheck', '查询发布结果', 'gray') + b('tsched', '📅 发布计划', 'line') + '<div class="mut" style="flex-basis:100%">公众号：已提交发布（异步处理，可查询结果）</div>';
  return '';
}

/* ---------- 事件 ---------- */
const ACT = {
  go: el => go(el.dataset.h), back: () => (history.length > 1 ? history.back() : go('#/home')),
  bell: () => go('#/msg'),
  openmsg: el => openMsg(el.dataset.id),
  readall: () => { const l = MSGS.load(); l.forEach(m => { m.read = true; }); MSGS.save(l); updateBadges(); R.msg(parse()); toast('已全部标为已读'); },
  clearmsg: () => { if (confirm('清空所有消息历史？')) { MSGS.save([]); updateBadges(); R.msg(parse()); } },
  savetk2: () => { const v = $('#tk').value.trim(); if (!v) return; LS.set('admin_token', v); LS.set('last_ev', null); pollEvents(); render(); },
  imode: el => { S.imode = el.dataset.v; document.querySelectorAll('[data-a=imode]').forEach(c => c.classList.toggle('on', c.dataset.v === S.imode)); },
  tplcsv: () => { const b = new Blob([csvTemplate()], { type: 'text/csv;charset=utf-8' }), a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = '店铺每日数据模板.csv'; document.body.appendChild(a); a.click(); a.remove(); },
  doimport: async () => {
    const csv = $('#csvtext').value.trim(); if (!csv) return toast('请先选择文件或粘贴 CSV 内容');
    $('#imsg').innerHTML = loading('正在导入…');
    try {
      const r = await api('/api/data/import', { csv, replace: S.imode === 'replace' }, { admin: true });
      S.iresult = `<div class="card" style="background:#e6f7f0;margin-top:10px">✅ 已导入 <b>${r.imported}</b> 行，跳过 ${r.skipped} 行<div class="mut">识别到的列：${esc(r.columns.join('、'))}；日期：${r.date_range[0]} 至 ${r.date_range[1]}</div>${r.errors.length ? `<div class="warn">${r.errors.map(esc).join('<br>')}</div>` : ''}</div>`;
      S.sum = null; S.xsum = {}; R.data(parse());
    } catch (e) { $('#imsg').innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  },
  cleardata: async () => { if (!confirm('确定清空已导入的所有数据？')) return; try { await api('/api/data/clear', {}, { admin: true }); S.sum = null; S.xsum = {}; S.iresult = ''; toast('已清空'); R.data(parse()); } catch (e) { toast(e.message); } },
  rundiag: async el => { $('#dgres').innerHTML = loading('正在检测，请稍候（会真实调用 Coze）…'); try { S.diagres = await api('/api/diagnose?wechat=' + (el.dataset.w || 0), null, { admin: true }); paintDiag(S.diagres); } catch (e) { $('#dgres').innerHTML = `<div class="err">${esc(e.message)}</div>`; } }, soon: () => toast('功能开发中'),
  menu: () => modal(`<h3>电商智研</h3><div class="mut" style="margin-bottom:12px">五大智能体一站式服务平台</div><div class="menu"><a data-a="go" data-h="#/home" data-close="1">🏠　首页</a><a data-a="about" data-close="1">ℹ️　关于我们</a></div>`),
  about: () => toast('电商智研 v1.0 · 五大AI助手'),
  ask: el => { const d = DOMAINS[+el.dataset.i]; S.chat = []; S.conv = null; go('#/wen/chat?q=' + encodeURIComponent(d[4])); },
  askq: el => { S.chat = []; S.conv = null; go('#/wen/chat?q=' + encodeURIComponent(el.dataset.q)); },
  send: () => sendQ(), askq2: el => sendQ(el.dataset.q),
  copytxt: el => copy(S.chat[+el.dataset.i].text), savetxt: () => toast('已保存'),
  newc: el => { S.form = el.dataset.t ? { type: el.dataset.t } : {}; go('#/chuang/new'); },
  tpl: el => { const t = TPL[+el.dataset.i][2]; S.form = { ...t }; go('#/chuang/new'); },
  soon2: () => { },
  pick: el => { readForm(); S.form[el.dataset.g] = el.dataset.v; R['chuang/new'](parse()); },
  gen: generate, copyres: () => copy([S.result.title, S.result.body, (S.result.hashtags || []).map(h => '#' + h).join(' ')].join('\n\n')),
  saveres: () => { const h = LS.get('chuang_hist', []); h.unshift({ ...S.result, title: S.result.title }); LS.set('chuang_hist', h.slice(0, 20)); toast('已保存到历史记录'); },
  openhist: el => { S.result = LS.get('chuang_hist', [])[+el.dataset.i]; go('#/chuang/result'); },
  queue: async () => { try { const t = await api('/api/publish/tasks', { title: S.result.title, digest: S.result.digest || '', body: S.result.body, hashtags: S.result.hashtags || [], topic: S.result.product || '' }, { admin: true }); toast('已加入发布队列 #' + t.id + (t.issues.length ? '（含合规风险，请先修改）' : '')); } catch (e) { toast(e.message); } },
  scene: el => { readDa(); S.daf.scene = el.dataset.v; R.da(parse()); }, dstyle: el => { readDa(); S.daf.style = el.dataset.v; R.da(parse()); },
  dbot: el => { readDa(); S.dabot = el.dataset.v; S.plans = null; R.da(parse()); }, dgen: genPlans, copyraw: () => copy(S.plans.raw || ''),
  dimg: async el => {
    const p = S.plans.plans[+el.dataset.i], f = S.daf;
    modal(`<h3>🖼️ 使用前后效果图</h3>${loading('正在生成，可能需要一分钟…')}`);
    try {
      const d = await api('/api/da/image', { text: `${p.name}：${(p.items || []).map(x => x.name).join('、')}；场景：${f.scene}；商品类型：${f.cat}；风格：${f.style}` });
      $('#modal .sheet').innerHTML = `<h3>🖼️ 使用前后效果图</h3>` + (d.images && d.images.length ? d.images.map(u => `<img src="${esc(u)}" style="width:100%;border-radius:12px;margin:8px 0">`).join('') : `<div class="card">${md(typeof d.data === 'string' ? d.data : JSON.stringify(d.data))}</div>`) + `<div class="mut">AI 生成的效果示意图，非真人实拍</div><button class="btn gray" data-a="closem">关闭</button>`;
    } catch (e) { $('#modal .sheet').innerHTML = `<h3>🖼️ 使用前后效果图</h3><div class="err">${esc(e.message)}</div><button class="btn gray" data-a="closem">关闭</button>`; }
  }, closem: () => closeModal(), script: el => $('#sc' + el.dataset.i).classList.toggle('open'), copyscript: el => copy(S.plans.plans[+el.dataset.i].sales_script || ''),
  rsel: el => { const c = custs().find(x => x.id === +el.dataset.id); S.custReplies[c.id].sel = +el.dataset.i; drawReplies(c); },
  rcopy: el => { const d = S.custReplies[+el.dataset.id]; copy(d.replies[d.sel || 0].text); },
  rsend: el => { const c = custs().find(x => x.id === +el.dataset.id), d = S.custReplies[c.id]; c.msgs.push(['a', d.replies[d.sel || 0].text]); c.time = '刚刚'; drawCust(c); toast('已发送'); },
  rreload: el => loadReplies(custs().find(x => x.id === +el.dataset.id), true),
  shop: el => { S.shop = el.dataset.v; S.custReplies = {}; R.fu(parse()); toast('已切换店铺'); },
  human: () => toast('已转接人工客服'), resolve: el => { const c = custs().find(x => x.id === +el.dataset.id); c.st = '已解决'; drawCust(c); toast('已标记为已解决'); },
  range: el => { S.range = el.dataset.v; R.xi(parse()); }, diag: diag, copydiag: () => { const d = S.diag.d; if (d.raw && !d.conclusion) return copy(d.raw); copy([d.conclusion, ...(d.evidence || []), ...(d.problems || []), ...(d.suggestions || []).map(s => s.action)].join('\n')); },
  savetk: () => { const v = $('#tk').value.trim(); if (!v) return; LS.set('admin_token', v); LS.set('last_ev', null); pollEvents(); R.publish(parse()); }, cleartk: () => { LS.set('admin_token', ''); R.publish(parse()); },
  reload: loadTasks,
  plan: async () => { $('#pst').innerHTML = loading('正在选题并生成…'); try { await api('/api/publish/plan', {}, { admin: true }); $('#pst').innerHTML = ''; toast('已生成，待审核'); } catch (e) { $('#pst').innerHTML = `<div class="err">${esc(e.message)}</div>`; } loadTasks(); },
  tappr: async el => { const id = +el.dataset.id; try { await api(`/api/publish/tasks/${id}/approve`, {}, { admin: true }); toast('已通过'); } catch (e) { if (confirm(e.message + '\n\n确认内容无误并强制通过？')) { try { await api(`/api/publish/tasks/${id}/approve?force=true`, {}, { admin: true }); toast('已通过'); } catch (e2) { toast(e2.message); } } } loadTasks(); },
  trej: async el => { try { await api(`/api/publish/tasks/${el.dataset.id}/reject`, {}, { admin: true }); } catch (e) { toast(e.message); } loadTasks(); },
  tpub: async el => { toast('正在写入…'); try { const t = await api(`/api/publish/tasks/${el.dataset.id}/publish`, {}, { admin: true }); toast(t.status === 'failed' ? '失败，见任务详情' : '已存入草稿箱'); } catch (e) { toast(e.message); } loadTasks(); },
  tpubd: async el => { toast('正在发布…'); try { const t = await api(`/api/publish/tasks/${el.dataset.id}/publish?direct=1`, {}, { admin: true }); toast(t.status === 'published' ? '已提交发布' : t.status === 'failed' ? '失败，见任务详情' : '已存入草稿箱，但提交发布失败（见任务详情）'); } catch (e) { toast(e.message); } loadTasks(); },
  tsubmit: async el => { toast('正在提交…'); try { const t = await api(`/api/publish/tasks/${el.dataset.id}/submit`, {}, { admin: true }); toast(t.status === 'published' ? '已提交发布' : '提交失败（见任务详情）'); } catch (e) { toast(e.message); } loadTasks(); },
  tcheck: async el => { try { const r = await api(`/api/publish/tasks/${el.dataset.id}/status`, null, { admin: true }); modal(`<h3>发布结果</h3><div class="card">${esc(r.text)}</div><div class="mut">发布编号：${esc(r.publish_id)}</div><button class="btn gray" data-a="closem">关闭</button>`); } catch (e) { toast(e.message); } },
  tsched: async el => {
    const id = +el.dataset.id; try { S.pinfo = await api('/api/publish/platforms', null, { admin: true }); } catch (e) { S.pinfo = []; }
    modal(`<h3>📅 发布计划 #${id}</h3>
      <label class="f">发布平台</label>
      <select class="in" id="s_plat"><option value="wechat">微信公众号</option><option value="xiaohongshu">小红书（辅助发布）</option><option value="douyin">抖音（辅助发布）</option><option value="wechat,xiaohongshu">公众号 + 小红书</option><option value="wechat,xiaohongshu,douyin">全部平台</option></select>
      <div class="mut" id="s_hint" style="margin-top:6px;line-height:1.6"></div>
      <label class="f">公众号发布方式</label>
      <select class="in" id="s_wmode"><option value="draft">存入草稿箱（手机上确认发布）</option><option value="publish">直接提交发布</option></select>
      <div class="mut" style="margin-top:4px">“直接提交发布”需要公众号有发布权限（通常需微信认证）；没有权限时内容仍会保留在草稿箱。</div>
      <label class="f">发布时间</label>
      <select class="in" id="s_when"><option value="now">立即</option><option value="30">30 分钟后</option><option value="60">1 小时后</option><option value="t20">今晚 20:00</option><option value="m9">明早 09:00</option><option value="custom">自定义时间…</option></select>
      <input class="in" id="s_dt" type="datetime-local" style="display:none;margin-top:8px">
      <button class="btn" data-a="ssave" data-id="${id}">确定</button>`);
    updHint();
  },
  ssave: async el => {
    const plats = $('#s_plat').value.split(','), w = $('#s_when').value, now = Date.now() / 1000; let run = null;
    if (w === '30' || w === '60') run = now + (+w) * 60;
    else if (w === 't20' || w === 'm9') { const d = new Date(); if (w === 't20') { d.setHours(20, 0, 0, 0); if (d.getTime() / 1000 <= now) d.setDate(d.getDate() + 1); } else { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); } run = d.getTime() / 1000; }
    else if (w === 'custom') { const v = $('#s_dt').value; if (!v) return toast('请选择时间'); run = new Date(v).getTime() / 1000; if (run <= now) return toast('请选择未来的时间'); }
    try { await api(`/api/publish/tasks/${el.dataset.id}/schedule`, { platforms: plats, run_at: run, wechat_mode: $('#s_wmode').value }, { admin: true }); closeModal(); toast(run ? '已安排发布计划' : '已执行'); } catch (e) { toast(e.message); }
    loadTasks();
  },
  scancel: async el => { try { await api(`/api/publish/schedules/${el.dataset.id}/cancel`, {}, { admin: true }); toast('已取消'); } catch (e) { toast(e.message); } loadTasks(); },
  scopy: el => { const x = Object.values(S.scheds || {}).flat().find(v => v.id === +el.dataset.id); if (x && x.result && x.result.content) copy(adaptedText(x.result.content)); },
  tedit: el => { const t = S.tasks.find(x => x.id === +el.dataset.id); modal(`<h3>编辑 #${t.id}</h3><label class="f">标题</label><input class="in" id="e_t" value="${esc(t.title)}"><label class="f">摘要</label><input class="in" id="e_d" value="${esc(t.digest)}"><label class="f">正文</label><textarea class="in" id="e_b" rows="10">${esc(t.body)}</textarea><button class="btn" data-a="esave" data-id="${t.id}">保存</button>`); },
  esave: async el => { try { await api('/api/publish/tasks/' + el.dataset.id, { title: $('#e_t').value, digest: $('#e_d').value, body: $('#e_b').value }, { admin: true, method: 'PATCH' }); closeModal(); toast('已保存'); } catch (e) { toast(e.message); } loadTasks(); }
};
function readDa() { const f = S.daf; if ($('#d_cat')) { f.cat = $('#d_cat').value.trim(); f.budget = $('#d_budget').value; f.aud = $('#d_aud').value.trim(); } }
function modal(html) { const m = $('#modal'); m.innerHTML = `<div class="sheet">${html}</div>`; m.classList.remove('hidden'); }
function closeModal() { $('#modal').classList.add('hidden'); }
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal' || e.target.closest('[data-close]')) { const a = e.target.closest('[data-a]'); closeModal(); if (a && ACT[a.dataset.a]) ACT[a.dataset.a](a); } else { const a = e.target.closest('[data-a]'); if (a && ACT[a.dataset.a]) ACT[a.dataset.a](a); } });
document.addEventListener('change', e => { if (e.target.id === 's_when') $('#s_dt').style.display = e.target.value === 'custom' ? 'block' : 'none'; if (e.target.id === 's_plat') updHint(); });
document.addEventListener('click', e => { if ($('#modal').contains(e.target)) return; const el = e.target.closest('[data-a]'); if (el && ACT[el.dataset.a]) ACT[el.dataset.a](el, e); });

/* ---------- 启动 ---------- */
(async function boot() {
  try { const h = await api('/api/health'); S.health = h; S.mock = !!h.mock_mode || Object.values(h.providers || {}).includes('mock'); S.mockAll = !!h.mock_mode; } catch (e) { /* 后端未启动时页面仍可浏览 */ }
  if (!LS.get('welcomed', 0)) { LS.set('welcomed', 1); pushMsg({ agent: 'sys', kind: 'info', title: '欢迎使用电商智研', summary: '点击这里，开始体验五大 AI 助手', payload: {} }, false); }
  render(); pollEvents(); setInterval(pollEvents, 20000);
})();
$('#notice').addEventListener('click', () => { const id = $('#notice').dataset.id; if (id) openMsg(id); });
