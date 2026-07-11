/**
 * LeetCode 式双语题解详情页渲染器。
 *
 * 依赖:
 *   - utils.js:apiFetch / escapeHtml(全站已加载)
 *   - markdown-it / markdown-it-container / DOMPurify(本页 CDN 加载)
 *   - MathJax(base.html 已加载,tex-svg)
 *
 * 渲染管线(见 docs/superpowers/specs/2026-07-11-bilingual-manning-contract.md §3):
 *   raw md → ①保护 $$…$$/$…$ 占位 → ②markdown-it(+container) → ③还原数学
 *          → ④DOMPurify.sanitize → ⑤注入 DOM 后 MathJax.typesetPromise。
 */
(function () {
  'use strict';

  var appEl = document.getElementById('qdApp');
  if (!appEl) return;
  var qid = appEl.dataset.qid;

  // ---------------------------------------------------------------- markdown-it
  var md = null;
  if (window.markdownit) {
    md = window.markdownit({ html: false, linkify: true, breaks: false, typographer: false });
    if (window.markdownitContainer) {
      registerContainer('def', '', '');            // 橙:定義/定理
      registerContainer('note', 'note', 'Note');   // 蓝:Note
      registerContainer('warn', 'warn', '注意');    // 红:注意/陷阱
      registerContainer('insight', 'note', 'Insight'); // 洞察 ≈ note
      registerContainer('conclusion', '__concl__', '結論');
    }
  }

  /** 注册一种 markdown-it-container,输出与 mockup 完全一致的 class 结构。 */
  function registerContainer(name, klass, defaultTitle) {
    md.use(window.markdownitContainer, name, {
      validate: function (params) {
        return params.trim().split(' ', 1)[0] === name;
      },
      render: function (tokens, idx) {
        var tok = tokens[idx];
        if (tok.nesting !== 1) return '</div>\n';
        var info = tok.info.trim();
        var title = info.slice(name.length).trim() || defaultTitle || '';
        if (klass === '__concl__') {
          return '<div class="conclusion"><span class="t">' +
                 md.utils.escapeHtml(title || '結論') + '</span>\n';
        }
        return '<div class="callout' + (klass ? ' ' + klass : '') + '">' +
               '<div class="t"><span class="mk"></span>' +
               md.utils.escapeHtml(title) + '</div>\n';
      }
    });
  }

  // ---------------------------------------------------------------- 数学占位
  function ph(i) { return 'QDMATHPLACEHOLDER' + i + 'ENDQD'; }

  /** ① 抽出 $$…$$ 与 $…$,替换为纯字母数字占位符(防 markdown 吞掉 _ / *)。 */
  function protectMath(src) {
    var store = [];
    function grab(m) { store.push(m); return ph(store.length - 1); }
    src = src.replace(/\$\$([\s\S]+?)\$\$/g, grab);   // 先 display
    src = src.replace(/\$((?:\\.|[^\$\\\n])+?)\$/g, grab); // 再 inline
    return { src: src, store: store };
  }

  /** ③ 还原数学占位。数学内部的 < > & 做 HTML 转义,保证随后 sanitize 不吞公式,
   *  MathJax 读取 textContent 时实体会被解码回原字符。分隔符 $ 保持原样。 */
  function restoreMath(html, store) {
    store.forEach(function (m, i) {
      var safe = m.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      html = html.split(ph(i)).join(safe);
    });
    return html;
  }

  // ---------------------------------------------------------------- 渲染
  var PURIFY_CFG = {
    ADD_TAGS: ['math', 'semantics', 'annotation', 'mrow', 'mi', 'mo', 'mn',
               'msup', 'msub', 'msubsup', 'mfrac', 'munder', 'mover', 'munderover',
               'msqrt', 'mroot', 'mtext', 'mspace', 'mtable', 'mtr', 'mtd'],
    ADD_ATTR: ['class', 'display', 'aria-hidden']
  };

  /** raw markdown → 经消毒的 HTML 字符串。缺库时降级为转义分段。 */
  function renderMarkdown(raw) {
    raw = raw || '';
    if (!md) {
      // 降级:无 markdown-it 时,至少按空行分段并转义,避免"一坨"。
      var esc = (window.escapeHtml || function (s) { return s; });
      return raw.split(/\n{2,}/).map(function (p) {
        return '<p>' + esc(p).replace(/\n/g, '<br>') + '</p>';
      }).join('');
    }
    var protectedSrc = protectMath(raw);
    var html = md.render(protectedSrc.src);              // ②
    html = restoreMath(html, protectedSrc.store);        // ③
    if (window.DOMPurify) html = window.DOMPurify.sanitize(html, PURIFY_CFG); // ④
    return html;
  }

  /** 注入 HTML 到节点并等 MathJax 排版(⑤)。 */
  function renderInto(node, raw) {
    node.innerHTML = renderMarkdown(raw);
  }

  // ---------------------------------------------------------------- MathJax
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

  // ---------------------------------------------------------------- DOM refs
  var el = {
    title: document.getElementById('qdTitle'),
    chips: document.getElementById('qdChips'),
    problem: document.getElementById('qdProblemBody'),
    trackJa: document.getElementById('qdTrackJa'),
    trackZh: document.getElementById('qdTrackZh'),
    navpills: document.getElementById('qdNavpills'),
    seg: document.querySelectorAll('.qd-seg button'),
    segJa: document.querySelector('.qd-seg button[data-track="ja"]'),
    segZh: document.querySelector('.qd-seg button[data-track="zh"]'),
    confidence: document.getElementById('qdConfidence')
  };
  var tracks = { ja: el.trackJa, zh: el.trackZh };
  var typesetDone = {};   // 惰性排版:轨首次显示时才 typeset

  // ---------------------------------------------------------------- 语言切换
  function buildNav(track) {
    el.navpills.innerHTML = '';
    var node = tracks[track];
    if (!node) return;
    var heads = node.querySelectorAll('h2');
    heads.forEach(function (h, i) {
      if (!h.id) h.id = 'qd-sec-' + track + '-' + i;
      var a = document.createElement('a');
      a.textContent = h.textContent;
      a.href = '#' + h.id;
      a.addEventListener('click', function (e) {
        e.preventDefault();
        h.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      el.navpills.appendChild(a);
    });
  }

  function pick(track) {
    Object.keys(tracks).forEach(function (k) {
      if (tracks[k]) tracks[k].classList.toggle('on', k === track);
    });
    el.seg.forEach(function (b) {
      b.setAttribute('aria-selected', String(b.dataset.track === track));
    });
    var node = tracks[track];
    if (node && !typesetDone[track]) {
      typesetDone[track] = true;
      typeset(node);
    }
    buildNav(track);
  }

  // ---------------------------------------------------------------- 题面/元信息
  function chipsHtml(q) {
    var esc = window.escapeHtml;
    var out = [];
    if (q.subject) out.push('<span class="qd-chip subject">' + esc(q.subject) + '</span>');
    if (q.difficulty) out.push('<span class="qd-chip diff">难度 ' + esc(q.difficulty) + '</span>');
    if (q.source) out.push('<span class="qd-chip"><span class="k">出典</span>' + esc(q.source) + '</span>');
    if (q.chapter) out.push('<span class="qd-chip">' + esc(q.chapter) + '</span>');
    (q.tags || []).forEach(function (t) {
      out.push('<span class="qd-chip">' + esc(t) + '</span>');
    });
    return out.join('');
  }

  function problemHtml(q) {
    var esc = window.escapeHtml;
    var parts = [renderMarkdown(q.question_latex) ||
                 '<p class="qd-empty">(无题目内容)</p>'];
    // 出典/科目 信息盒
    var rows = [];
    if (q.source) rows.push('<div class="r"><span>出典</span><span>' + esc(q.source) + '</span></div>');
    if (q.subject) {
      rows.push('<div class="r"><span>科目</span><span>' + esc(q.subject) +
                (q.chapter ? ' · ' + esc(q.chapter) : '') + '</span></div>');
    }
    if (rows.length) parts.push('<div class="qd-srcbox">' + rows.join('') + '</div>');
    // 原题图片
    if (q.question_image_url) {
      if (/\.pdf$/i.test(q.question_image || q.question_image_url)) {
        parts.push('<div class="qd-figph"><a class="qd-srcbox" href="' + esc(q.question_image_url) +
                   '" target="_blank" rel="noopener">查看原题 PDF ↗</a></div>');
      } else {
        parts.push('<div class="qd-fig"><a href="' + esc(q.question_image_url) +
                   '" target="_blank" rel="noopener"><img src="' + esc(q.question_image_url) +
                   '" alt="原题图"></a></div>');
      }
    }
    return parts.join('');
  }

  // ---------------------------------------------------------------- 装载
  function load() {
    apiFetch('/api/questions/' + qid).then(function (resp) {
      var q = resp.data.question;

      el.title.textContent = q.source || ('题目 #' + q.id);
      el.chips.innerHTML = chipsHtml(q);
      el.problem.innerHTML = problemHtml(q);
      typeset(el.problem);

      var ja = (q.solution_ja || '').trim();
      var zh = (q.solution_latex || '').trim();
      renderInto(el.trackJa, ja);
      renderInto(el.trackZh, zh);

      var hasJa = !!ja, hasZh = !!zh;
      // JA 为空:隐藏日本語标签,只显示中文
      if (!hasJa) el.segJa.hidden = true;
      if (!hasZh && hasJa) el.segZh.hidden = true;

      if (!hasJa && !hasZh) {
        el.trackZh.classList.add('on');
        el.trackZh.innerHTML = '<p class="qd-empty">(暂无题解)</p>';
        el.confidence.hidden = true;
        return;
      }
      el.confidence.textContent = '';
      var dot = document.createElement('span'); dot.className = 'd';
      el.confidence.appendChild(dot);
      el.confidence.appendChild(document.createTextNode(
        hasJa && hasZh ? '双轨题解 · bilingual' : (hasJa ? '日本語詳解' : '中文速览')));

      pick(hasJa ? 'ja' : 'zh');   // 默认日本語(有则),否则中文

      // 记录查看日志(静默)
      apiFetch('/api/log_view_question', { method: 'POST', body: { question_id: Number(qid) } })
        .catch(function () {});
    }).catch(function (e) {
      el.problem.innerHTML = '<p class="qd-empty">加载失败:' +
        (window.escapeHtml ? window.escapeHtml(e.message) : e.message) + '</p>';
    });
  }

  // ---------------------------------------------------------------- 交互
  el.seg.forEach(function (b) {
    b.addEventListener('click', function () { pick(b.dataset.track); });
  });

  // 明暗主题切换(设 data-theme 到 <html>)
  var themeBtn = document.getElementById('qdThemeBtn');
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var root = document.documentElement;
      var cur = root.getAttribute('data-theme');
      var prefersDark = window.matchMedia &&
        window.matchMedia('(prefers-color-scheme: dark)').matches;
      var next = cur === 'dark' ? 'light' : (cur === 'light' ? 'dark' : (prefersDark ? 'light' : 'dark'));
      root.setAttribute('data-theme', next);
    });
  }

  // 分栏拖拽
  var gutter = document.getElementById('qdGutter');
  var split = document.getElementById('qdSplit');
  if (gutter && split) {
    var dragging = false;
    gutter.addEventListener('mousedown', function (e) {
      dragging = true; e.preventDefault(); document.body.style.userSelect = 'none';
    });
    window.addEventListener('mouseup', function () {
      dragging = false; document.body.style.userSelect = '';
    });
    window.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      var r = split.getBoundingClientRect();
      var pct = (e.clientX - r.left) / r.width * 100;
      pct = Math.max(28, Math.min(64, pct));
      split.style.gridTemplateColumns =
        'minmax(0,' + pct.toFixed(1) + 'fr) 9px minmax(0,' + (100 - pct).toFixed(1) + 'fr)';
    });
  }

  load();
})();
