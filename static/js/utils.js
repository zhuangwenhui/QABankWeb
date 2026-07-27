/**
 * 通用工具函数(全站共用)。
 */

/** 读取页面 meta 中的 CSRF token */
function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
}

/**
 * fetch 封装:自动附带 CSRF header 与同源 Cookie,统一解析 JSON。
 * 后端统一响应格式 { success, data?, error?, code? }。
 * 成功时 resolve 整个响应对象;失败时抛出 Error(err.code / err.payload 可用)。
 */
async function apiFetch(url, options = {}) {
  const opts = Object.assign({ credentials: 'same-origin' }, options);
  opts.headers = Object.assign({ 'X-CSRFToken': getCsrfToken() }, options.headers || {});
  if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== 'string') {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  const resp = await fetch(url, opts);
  let payload = null;
  try {
    payload = await resp.json();
  } catch (e) {
    throw Object.assign(new Error(`服务器响应异常 (HTTP ${resp.status})`), { status: resp.status });
  }
  if (!resp.ok || payload.success === false) {
    const err = new Error((payload && payload.error) || `请求失败 (HTTP ${resp.status})`);
    err.code = payload && payload.code;
    err.status = resp.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

/** 对象转查询字符串,自动忽略空值 */
function buildQuery(params) {
  const usp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && String(v) !== '') usp.append(k, v);
  });
  const s = usp.toString();
  return s ? `?${s}` : '';
}

/** HTML 转义,防止 XSS(同时转义引号,可安全用于双/单引号属性值) */
function escapeHtml(text) {
  if (text == null) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** 防抖 */
function debounce(fn, wait = 300) {
  let timer = null;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), wait);
  };
}

/**
 * 请求重排数学公式。
 *
 * 有共享管线(qd_render.js)时一律委托给它:排版必须全站走**同一条串行队列**,
 * 两条队列并发作用于同一批文本节点会让 MathJax 抛 splitText offset 错,整块公式
 * 停在源码态(2026-07-26 详情弹窗即此)。没有管线的页面才走这里的极简实现。
 */
let __mathChain = Promise.resolve();
function typesetMath(el) {
  if (window.QDRender && window.QDRender.typeset) return window.QDRender.typeset(el);
  __mathChain = __mathChain.then(() => {
    if (!(window.MathJax && window.MathJax.typesetPromise)) return;
    return new Promise((done) => {
      const t = setTimeout(() => { console.warn('MathJax 排版超时'); done(); }, 20000);
      try { if (MathJax.typesetClear) MathJax.typesetClear(); } catch (e) { /* 忽略 */ }
      MathJax.typesetPromise().then(
        () => { clearTimeout(t); done(); },
        (e) => { clearTimeout(t); console.warn('MathJax 渲染失败:', e); done(); });
    });
  }).catch((e) => { console.warn('MathJax 排版链异常:', e); });
  return __mathChain;
}

/** 难度 → 样式类(简单绿 / 中等黄 / 困难红) */
function difficultyClass(difficulty) {
  return { '简单': 'difficulty-easy', '中等': 'difficulty-medium', '困难': 'difficulty-hard' }[difficulty] || 'difficulty-medium';
}

/** 难度徽章 HTML */
function difficultyBadge(difficulty) {
  return `<span class="difficulty-badge ${difficultyClass(difficulty)}">${escapeHtml(difficulty)}</span>`;
}

/** 标签数组 → 徽章 HTML */
function tagBadges(tags) {
  return (tags || []).map((t) => `<span class="tag-badge">${escapeHtml(t)}</span>`).join('');
}

/** 格式化日期字符串(后端返回 'YYYY-MM-DD HH:MM:SS') */
function formatDate(s, withTime = false) {
  if (!s) return '';
  return withTime ? s : s.split(' ')[0];
}

/** 两位补零 */
function pad2(n) {
  return String(n).padStart(2, '0');
}

/**
 * Date → 'YYYY-MM-DD',按**本地时区**。
 *
 * 不能图省事写 d.toISOString().slice(0, 10):那个是 UTC,JST 上午 9 点前会算成前一天,
 * PDF 的默认考试日期就会莫名其妙少一天。
 */
function formatLocalDate(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/**
 * 分页页码序列(带省略号),如 [1, '...', 4, 5, 6, '...', 20]。
 * 首尾页恒显示,当前页两侧各留 2 页,断档处插一个 '...'。
 *
 * 题库列表与错题本此前各写了一份(pageNumbers / pageWindow),实现思路不同但输出等价 ——
 * total 1..80 × current 全组合共 3240 组穷举比对过,结果数组完全一致,故合并为这一份。
 * 注意这里只算**页码序列**;两页的分页条外观是刻意不同的(题库用 «» 实体且单页仍渲染
 * 分页条,错题本用 fa-angle 图标且 pages<=1 直接不渲染),那部分留在各自文件里。
 */
function pageNumbers(current, total) {
  const wanted = new Set([1, total, current - 2, current - 1, current, current + 1, current + 2]);
  const nums = Array.from(wanted).filter((n) => n >= 1 && n <= total).sort((a, b) => a - b);
  const out = [];
  let prev = 0;
  nums.forEach((n) => {
    if (n - prev > 1) out.push('...');
    out.push(n);
    prev = n;
  });
  return out;
}
