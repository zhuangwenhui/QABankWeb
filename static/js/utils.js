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
 * 对指定元素(或整页)重新渲染 MathJax 公式。
 *
 * MathJax v4.1.3 的 typesetPromise 实测会永久挂起(不 settle,也不在等任何网络请求),
 * 而同步版 MathJax.typeset 正常。只等 Promise 会让动态插入的公式永远停在 LaTeX 源码态 ——
 * 2026-07-25 线上事故即此。故加超时 + 同步兜底,与 qd_render.js 同一策略。
 */
function typesetMath(el) {
  const nodes = el ? [el] : undefined;
  const trySync = () => {
    if (!(window.MathJax && window.MathJax.typeset)) return false;
    try {
      MathJax.typeset(nodes);
      return true;
    } catch (e) {
      if (String(e).includes('retry')) return 'retry';
      console.warn('MathJax 同步排版失败:', e);
      return false;
    }
  };
  return new Promise((done) => {
    let kicked = false;
    const attempt = (n) => {
      const r = trySync();
      if (r === true || r === false || n >= 4) return done();
      if (!kicked && window.MathJax && window.MathJax.typesetPromise) {
        kicked = true;   // 促发按需加载,不等它 settle(可能永不 settle)
        MathJax.typesetPromise(nodes).then(done, () => {});
        setTimeout(() => attempt(n + 1), 1500);
      } else {
        setTimeout(() => attempt(n + 1), 900);
      }
    };
    attempt(0);
  });
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
