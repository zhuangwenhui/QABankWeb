/**
 * 间隔复习页:到期错题逐题揭示题解 + 四键自评(SM-2 排期)。
 *
 * 依赖:
 *   - utils.js:apiFetch / escapeHtml / showToast(全站已加载)
 *   - markdown-it / markdown-it-container / DOMPurify(本页 CDN 加载)
 *   - MathJax v4(base.html 已加载,tex-svg)
 *
 * 渲染管线 renderMd(raw, track, el) 为 question_detail.js 的精简自包含副本:
 *   raw md → ①保护 $$…$$/$…$ 占位 → ②markdown-it(+container) → ③还原数学
 *          → ④DOMPurify.sanitize → ⑤注入 DOM 后 MathJax.typesetPromise。
 * 与详情页一致:保留 MathJax v4 原生行为,不做「文本组内 \_→_ 还原」改写。
 */
(function () {
  'use strict';

  var appEl = document.getElementById('rvApp');
  if (!appEl) return;

  // ============================================================ 渲染副本(renderMd)
  var LABELS = {
    ja: { def: '定義・定理', note: 'Note', warn: '注意', insight: '洞察', conclusion: '結論' },
    zh: { def: '定义·定理', note: '提示', warn: '注意', insight: '洞察', conclusion: '结论' }
  };
  var activeTrack = 'ja';

  var md = null;
  if (window.markdownit) {
    md = window.markdownit({ html: false, linkify: true, breaks: false, typographer: false });
    if (window.markdownitContainer) {
      registerContainer('def', '');
      registerContainer('note', 'note');
      registerContainer('warn', 'warn');
      registerContainer('insight', 'note');
      registerContainer('conclusion', '__concl__');
    }
  }

  function registerContainer(name, klass) {
    md.use(window.markdownitContainer, name, {
      validate: function (params) {
        return params.trim().split(' ', 1)[0] === name;
      },
      render: function (tokens, idx) {
        var tok = tokens[idx];
        if (tok.nesting !== 1) return '</div>\n';
        var info = tok.info.trim();
        var byTrack = (LABELS[activeTrack] || LABELS.ja)[name] || '';
        var title = info.slice(name.length).trim() || byTrack;
        if (klass === '__concl__') {
          return '<div class="conclusion"><span class="t">' +
                 md.utils.escapeHtml(title) + '</span>\n';
        }
        return '<div class="callout' + (klass ? ' ' + klass : '') + '">' +
               '<div class="t"><span class="mk"></span>' +
               md.utils.escapeHtml(title) + '</div>\n';
      }
    });
  }

  function ph(i) { return 'RVMATHPLACEHOLDER' + i + 'ENDRV'; }

  // MathJax v4 原生正确渲染文本模式里的转义 \_ 与 \&,无需改写(详见 question_detail.js 注释)。
  function fixTextModeEscapes(tex) { return tex; }

  function protectMath(src) {
    var store = [];
    function grab(m) { store.push(fixTextModeEscapes(m)); return ph(store.length - 1); }
    src = src.replace(/\$\$([\s\S]+?)\$\$/g, grab);        // 先 display
    src = src.replace(/\$((?:\\.|[^\$\\\n])+?)\$/g, grab); // 再 inline
    return { src: src, store: store };
  }

  function restoreMath(html, store) {
    store.forEach(function (m, i) {
      var safe = m.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      html = html.split(ph(i)).join(safe);
    });
    return html;
  }

  var PURIFY_CFG = {
    ADD_TAGS: ['math', 'semantics', 'annotation', 'mrow', 'mi', 'mo', 'mn',
               'msup', 'msub', 'msubsup', 'mfrac', 'munder', 'mover', 'munderover',
               'msqrt', 'mroot', 'mtext', 'mspace', 'mtable', 'mtr', 'mtd'],
    ADD_ATTR: ['class', 'display', 'aria-hidden']
  };

  function renderMarkdown(raw, track) {
    raw = raw || '';
    activeTrack = (track === 'zh') ? 'zh' : 'ja';
    if (!md) {
      var esc = (window.escapeHtml || function (s) { return s; });
      return raw.split(/\n{2,}/).map(function (p) {
        return '<p>' + esc(p).replace(/\n/g, '<br>') + '</p>';
      }).join('');
    }
    var protectedSrc = protectMath(raw);
    var html = md.render(protectedSrc.src);
    html = restoreMath(html, protectedSrc.store);
    if (window.DOMPurify) html = window.DOMPurify.sanitize(html, PURIFY_CFG);
    return html;
  }

  var STEP_RE = /^\s*(第[一二三四五六七八九十百千]+步|Step\s*\d+|\d+)\s*[:：.、)]?\s*/;
  function enhanceSteps(node) {
    node.querySelectorAll('h3').forEach(function (h) {
      var tn = h.firstChild;
      if (tn && tn.nodeType === 3) {
        var m = tn.nodeValue.match(STEP_RE);
        if (m) {
          var chip = document.createElement('span');
          chip.className = 'n';
          chip.textContent = m[1];
          tn.nodeValue = tn.nodeValue.slice(m[0].length);
          h.insertBefore(chip, tn);
          h.classList.add('qd-h3-chip');
          return;
        }
      }
      h.classList.add('qd-h3-plain');
    });
  }

  function mathReady() {
    if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
      return window.MathJax.startup.promise;
    }
    return new Promise(function (res) {
      setTimeout(function () { mathReady().then(res); }, 50);
    });
  }
  function typeset(node) {
    return mathReady().then(function () {
      if (window.MathJax && window.MathJax.typesetPromise) {
        return window.MathJax.typesetPromise([node]);
      }
    }).catch(function (e) { console.warn('MathJax 渲染失败:', e); });
  }

  /** raw markdown → 消毒 HTML 注入 node,强化步骤块,排版数学。track 决定容器默认标签。 */
  function renderMd(raw, track, node) {
    node.innerHTML = renderMarkdown(raw, track);
    enhanceSteps(node);
    return typeset(node);
  }

  // ============================================================ 复习流程
  var esc = window.escapeHtml || function (s) { return s; };
  var el = {
    body: document.getElementById('rvBody'),
    chips: document.getElementById('rvChips'),
    title: document.getElementById('rvTitle'),
    progress: document.getElementById('rvProgress'),
    index: document.getElementById('rvIndex'),
    total: document.getElementById('rvTotal'),
    bar: document.getElementById('rvBar'),
    barFill: document.getElementById('rvBarFill')
  };

  var queue = [];        // due 到期条目
  var pos = 0;           // 当前索引
  var reviewedCount = 0; // 本次已评题数

  function chipsHtml(q) {
    var out = [];
    if (q.subject) out.push('<span class="qd-chip subject">' + esc(q.subject) + '</span>');
    if (q.difficulty) out.push('<span class="qd-chip diff">难度 ' + esc(q.difficulty) + '</span>');
    if (q.source) out.push('<span class="qd-chip"><span class="k">出典</span>' + esc(q.source) + '</span>');
    if (q.chapter) out.push('<span class="qd-chip">' + esc(q.chapter) + '</span>');
    (q.tags || []).forEach(function (t) { out.push('<span class="qd-chip">' + esc(t) + '</span>'); });
    return out.join('');
  }

  function updateProgress() {
    el.progress.hidden = false;
    el.bar.hidden = false;
    el.index.textContent = Math.min(pos + 1, queue.length);
    el.total.textContent = queue.length;
    var pct = queue.length ? (pos / queue.length) * 100 : 0;
    el.barFill.style.width = pct.toFixed(1) + '%';
  }

  function showDone() {
    el.progress.hidden = true;
    el.bar.hidden = true;
    el.title.textContent = '间隔复习';
    el.chips.innerHTML = '';
    var body = reviewedCount
      ? '<h2>本次复习完成</h2><p>共复习 ' + reviewedCount + ' 题,继续保持!</p>'
      : '<h2>今日复习完成</h2><p>当前没有到期的复习题,去做点新题吧。</p>';
    el.body.innerHTML =
      '<div class="rv-done"><div class="rv-done-emoji">🎉</div>' + body +
      '<a class="rv-link" href="/questions">返回题库</a></div>';
  }

  function renderCard(entry) {
    var q = entry.question || {};
    var ja = (q.solution_ja || '').trim();
    var zh = (q.solution_latex || '').trim();
    var solTrack = ja ? 'ja' : 'zh';
    var solRaw = ja || zh;

    el.title.textContent = q.source || ('题目 #' + q.id);
    el.chips.innerHTML = chipsHtml(q);
    updateProgress();

    el.body.innerHTML =
      '<div class="rv-card">' +
        '<section class="rv-panel"><p class="qd-kicker">問題</p>' +
          '<div class="qd-prob" id="rvProblem" lang="ja"></div></section>' +
        '<div class="rv-reveal" id="rvRevealWrap">' +
          '<button type="button" class="rv-reveal-btn" id="rvReveal">揭示题解</button></div>' +
        '<section class="rv-panel rv-solution" id="rvSolWrap" hidden>' +
          '<p class="qd-kicker">題解</p>' +
          '<div class="solbody"><div class="qd-track on" id="rvSolution" lang="' +
            (solTrack === 'ja' ? 'ja' : 'zh-CN') + '"></div></div>' +
          '<div class="rv-rate">' +
            '<p class="rv-rate-hint">自评掌握程度</p>' +
            '<div class="rv-rate-btns" id="rvRateBtns">' +
              '<button type="button" class="rv-r again" data-rating="again">再来</button>' +
              '<button type="button" class="rv-r hard" data-rating="hard">困难</button>' +
              '<button type="button" class="rv-r good" data-rating="good">良好</button>' +
              '<button type="button" class="rv-r easy" data-rating="easy">掌握</button>' +
            '</div></div>' +
        '</section>' +
      '</div>';

    var probEl = document.getElementById('rvProblem');
    if ((q.question_latex || '').trim()) renderMd(q.question_latex, 'ja', probEl);
    else probEl.innerHTML = '<p class="rv-empty">(无题目内容)</p>';

    var revealWrap = document.getElementById('rvRevealWrap');
    var solWrap = document.getElementById('rvSolWrap');
    document.getElementById('rvReveal').addEventListener('click', function () {
      revealWrap.hidden = true;
      solWrap.hidden = false;
      var solEl = document.getElementById('rvSolution');
      if (solRaw) renderMd(solRaw, solTrack, solEl);
      else solEl.innerHTML = '<p class="rv-empty">(暂无题解)</p>';
      solWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });

    var rateBtns = solWrap.querySelectorAll('.rv-r');
    rateBtns.forEach(function (b) {
      b.addEventListener('click', function () {
        rateBtns.forEach(function (x) { x.disabled = true; });   // 防重复提交
        rate(entry.question_id, b.dataset.rating, rateBtns);
      });
    });
  }

  function rate(qid, rating, rateBtns) {
    apiFetch('/api/review/rate', { method: 'POST', body: { question_id: qid, rating: rating } })
      .then(function () {
        reviewedCount++;
        pos++;
        next();
      }).catch(function (e) {
        rateBtns.forEach(function (x) { x.disabled = false; });   // 失败复原,允许重试
        if (window.showToast) window.showToast(e.message || '记录失败,请重试', 'danger');
      });
  }

  function next() {
    if (pos >= queue.length) { showDone(); return; }
    renderCard(queue[pos]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function load() {
    apiFetch('/api/review/due?limit=20').then(function (resp) {
      queue = ((resp.data && resp.data.entries) || []).filter(function (e) {
        return e && e.question;
      });
      pos = 0;
      reviewedCount = 0;
      if (!queue.length) { showDone(); return; }
      next();
    }).catch(function (e) {
      el.body.innerHTML = '<p class="rv-empty">加载失败:' + esc(e.message) + '</p>';
    });
  }

  load();
})();
