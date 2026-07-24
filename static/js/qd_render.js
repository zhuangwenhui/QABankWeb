/**
 * 共享渲染管线(window.QDRender)。
 *
 * 此前 question_detail.js 与 review.js 各持一份字节等价的副本(Manning 块语汇 + MathJax v4
 * 管线),改渲染须两处同步、漏一处即静默漂移(已发生过)。此处抽出为单一实现,两页共用。
 *
 * 管线:raw md → ①保护 $$…$$/$…$ 占位 → ②markdown-it(+container) → ③还原数学
 *      → ④DOMPurify.sanitize → ⑤注入 DOM 后 MathJax.typesetPromise。
 * 保留 MathJax v4 原生行为:不做「文本组内 \_→_ 还原」改写(v4 原生正确渲染转义 \_ \&)。
 *
 * 依赖:markdown-it / markdown-it-container / DOMPurify(模板自托管加载)、MathJax v4(base.html)、
 *       utils.js 的 escapeHtml。缺库时优雅降级(分段转义 / 跳过消毒)。
 */
(function () {
  'use strict';

  // 容器默认标题按轨取,防中日混搭(渲染前置 activeTrack)。
  var LABELS = {
    ja: { def: '定義・定理', note: 'Note', warn: '注意', insight: '洞察', conclusion: '結論' },
    zh: { def: '定义·定理', note: '提示', warn: '注意', insight: '洞察', conclusion: '结论' }
  };
  var activeTrack = 'ja';

  var md = null;
  if (window.markdownit) {
    md = window.markdownit({ html: false, linkify: true, breaks: false, typographer: false });
    if (window.markdownitContainer) {
      registerContainer('def', '');            // 橙:定義/定理
      registerContainer('note', 'note');       // 蓝:Note
      registerContainer('warn', 'warn');       // 红:注意/陷阱
      registerContainer('insight', 'note');    // 洞察 ≈ note
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

  function ph(i) { return 'QDMATHPLACEHOLDER' + i + 'ENDQD'; }

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

  /** raw markdown → 经消毒的 HTML 字符串。track 决定容器默认标签。缺库降级为转义分段。 */
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

  /** 注入 HTML + 强化步骤块(不 typeset;调用方按需自行 typeset)。 */
  function renderInto(node, raw, track) {
    node.innerHTML = renderMarkdown(raw, track);
    enhanceSteps(node);
  }

  /** 注入 + 强化 + 排版数学(含 typeset,返回其 Promise)。 */
  function renderMd(raw, track, node) {
    node.innerHTML = renderMarkdown(raw, track);
    enhanceSteps(node);
    return typeset(node);
  }

  // 采点结构化题解四段:方針蓝/答案例橙/失点红/部分点绿。整块空则隐藏。
  var STRUCT_SECTIONS = [
    { key: 'houshin', label: '解答方針', kind: 'houshin' },
    { key: 'model',   label: '答案例',   kind: 'model' },
    { key: 'shitten', label: '典型失点', kind: 'shitten' },
    { key: 'haiten',  label: '部分点分布', kind: 'haiten' }
  ];
  function renderStructuredInto(node, s) {
    if (!node) return;
    s = s || {};
    var esc = window.escapeHtml || function (x) { return x; };
    var has = STRUCT_SECTIONS.some(function (sec) { return (s[sec.key] || '').trim(); });
    if (!has) { node.hidden = true; return; }
    node.hidden = false;
    node.innerHTML = '<div class="qd-struct-head">採点ポイント · 采点结构化</div>' +
                     '<div class="qd-struct-grid"></div>';
    var grid = node.querySelector('.qd-struct-grid');
    STRUCT_SECTIONS.forEach(function (sec) {
      var raw = (s[sec.key] || '').trim();
      if (!raw) return;
      var card = document.createElement('div');
      card.className = 'qd-struct-card ' + sec.kind;
      card.innerHTML = '<div class="qd-struct-card-h"><span class="qd-struct-bar"></span>' +
                       '<span class="qd-struct-t">' + esc(sec.label) + '</span></div>' +
                       '<div class="qd-struct-b solbody"></div>';
      grid.appendChild(card);
      renderMd(raw, 'ja', card.querySelector('.qd-struct-b'));
    });
  }

  window.QDRender = {
    LABELS: LABELS,
    PURIFY_CFG: PURIFY_CFG,
    renderMarkdown: renderMarkdown,
    renderInto: renderInto,
    renderMd: renderMd,
    typeset: typeset,
    mathReady: mathReady,
    enhanceSteps: enhanceSteps,
    STRUCT_SECTIONS: STRUCT_SECTIONS,
    renderStructuredInto: renderStructuredInto
  };
})();
