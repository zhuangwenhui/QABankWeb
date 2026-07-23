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

  // 容器默认标题按轨取(显式标题仍优先)。防止中文轨渲出日文标签(反之亦然)——
  // 即用户强调的"中日混搭"。渲染前置 activeTrack,容器 render 据此选默认标签。
  var LABELS = {
    ja: { def: '定義・定理', note: 'Note', warn: '注意', insight: '洞察', conclusion: '結論' },
    zh: { def: '定义·定理', note: '提示', warn: '注意', insight: '洞察', conclusion: '结论' }
  };
  var activeTrack = 'ja';

  // ---------------------------------------------------------------- markdown-it
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

  /** 注册一种 markdown-it-container,输出与 mockup 完全一致的 class 结构。
   *  无显式标题时,按当前 activeTrack 取该轨默认标签(避免中日混搭)。 */
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

  // ---------------------------------------------------------------- 数学占位
  function ph(i) { return 'QDMATHPLACEHOLDER' + i + 'ENDQD'; }

  // MathJax v4 原生正确渲染文本模式(\text/\texttt/…)里的转义 \_ 与 \&,无需改写。
  // 历史上为 MathJax v3 做的「文本组内 \_→_ 还原」在 v4 下反而会触发
  // "'_' allowed only in math mode"(裸 _ 在文本模式非法)——源码本就用转义 \_,
  // 被改写成裸 _ 后 v4 报错。实测 v4 下 \texttt{compare\_swap} 正常、compare_swap 报错,
  // 故彻底移除该改写,保持原样交给 MathJax v4。
  function fixTextModeEscapes(tex) {
    return tex;
  }

  /** ① 抽出 $$…$$ 与 $…$,替换为纯字母数字占位符(防 markdown 吞掉 _ / *)。 */
  function protectMath(src) {
    var store = [];
    function grab(m) { store.push(fixTextModeEscapes(m)); return ph(store.length - 1); }
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

  /** raw markdown → 经消毒的 HTML 字符串。track 决定容器默认标签(ja/zh)。缺库时降级为转义分段。 */
  function renderMarkdown(raw, track) {
    raw = raw || '';
    activeTrack = (track === 'zh') ? 'zh' : 'ja';
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

  // ### 步骤标题:把"第N步/编号"前缀包成 .n 徽标。只动首个文本节点,保留标题内行内公式。
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

  /** 注入 HTML 到节点、强化步骤块,并等 MathJax 排版(⑤)。track 决定容器默认标签。 */
  function renderInto(node, raw, track) {
    node.innerHTML = renderMarkdown(raw, track);
    enhanceSteps(node);
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
    hints: document.getElementById('qdHints'),
    structured: document.getElementById('qdStructured'),
    trackJa: document.getElementById('qdTrackJa'),
    trackZh: document.getElementById('qdTrackZh'),
    navpills: document.getElementById('qdNavpills'),
    seg: document.querySelectorAll('.qd-seg button'),
    segJa: document.querySelector('.qd-seg button[data-track="ja"]'),
    segZh: document.querySelector('.qd-seg button[data-track="zh"]'),
    confidence: document.getElementById('qdConfidence'),
    masteryBtns: document.querySelectorAll('#qdMastery button')
  };
  var tracks = { ja: el.trackJa, zh: el.trackZh };
  var typesetDone = {};   // 惰性排版:轨首次显示时才 typeset
  var spy = [];           // scrollspy:[{h2, link}]

  // ---------------------------------------------------------------- 掌握状态(做题进度)
  // 与列表页同轴:done/mastered 落库,none 删行(未做)。仅读写进度,不触渲染管线。
  var masteryStatus = null;   // null(未做)| 'done' | 'mastered'
  function paintMastery() {
    el.masteryBtns.forEach(function (b) {
      var s = b.dataset.status;
      var on = (s === 'none') ? (masteryStatus === null) : (s === masteryStatus);
      b.classList.toggle('active', on);
      b.setAttribute('aria-pressed', String(on));
    });
  }
  function initMastery() {
    apiFetch('/api/progress/check_batch', { method: 'POST', body: { question_ids: [Number(qid)] } })
      .then(function (resp) {
        var statuses = (resp.data && resp.data.statuses) || {};
        masteryStatus = statuses[String(qid)] || null;
        paintMastery();
      }).catch(function () { paintMastery(); });
  }
  el.masteryBtns.forEach(function (b) {
    b.addEventListener('click', function () {
      var status = b.dataset.status;   // done | mastered | none
      apiFetch('/api/progress/set', { method: 'POST', body: { question_id: Number(qid), status: status } })
        .then(function () {
          masteryStatus = (status === 'none') ? null : status;
          paintMastery();
          if (window.showToast) {
            window.showToast(status === 'none' ? '已标记为未做'
              : (status === 'mastered' ? '已标记为掌握' : '已标记为做过'), 'success');
          }
        }).catch(function (e) {
          if (window.showToast) window.showToast(e.message, 'danger');
        });
    });
  });

  // ---------------------------------------------------------------- 语言切换 + 章节导航
  function buildNav(track) {
    el.navpills.innerHTML = '';
    spy = [];
    var node = tracks[track];
    if (!node) return;
    node.querySelectorAll('h2').forEach(function (h, i) {
      if (!h.id) h.id = 'qd-sec-' + track + '-' + i;
      var a = document.createElement('a');
      a.textContent = h.textContent;
      a.href = '#' + h.id;
      a.addEventListener('click', function (e) {
        e.preventDefault();
        h.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      el.navpills.appendChild(a);
      spy.push({ h2: h, link: a });
    });
    updateSpy();
  }

  // 高亮当前章节:取视口上沿(留出粘性工具栏偏移)之上、最靠下的 h2。
  function updateSpy() {
    if (!spy.length) return;
    var offset = 100, active = 0;
    for (var i = 0; i < spy.length; i++) {
      if (spy[i].h2.getBoundingClientRect().top - offset <= 0) active = i;
    }
    spy.forEach(function (s, i) { s.link.classList.toggle('active', i === active); });
  }
  var spyScheduled = false;
  window.addEventListener('scroll', function () {
    if (spyScheduled) return;
    spyScheduled = true;
    requestAnimationFrame(function () { spyScheduled = false; updateSpy(); });
  }, { passive: true });

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
    // 规范化知识点标签:可点,跳到列表页并预筛该知识点(标签联动)
    (q.knowledge_tags || []).forEach(function (t) {
      out.push('<a class="qd-chip ktag" href="/questions?knowledgeTags=' +
               encodeURIComponent(t) + '" title="按此知识点筛选题库">' + esc(t) + '</a>');
    });
    return out.join('');
  }

  function problemHtml(q) {
    var esc = window.escapeHtml;
    var parts = [renderMarkdown(q.question_latex, 'ja') ||
                 '<p class="qd-empty">(无题目内容)</p>'];
    // 出典/科目 信息盒
    var rows = [];
    if (q.source) rows.push('<div class="r"><span>出典</span><span>' + esc(q.source) + '</span></div>');
    if (q.subject) {
      rows.push('<div class="r"><span>科目</span><span>' + esc(q.subject) +
                (q.chapter ? ' · ' + esc(q.chapter) : '') + '</span></div>');
    }
    // 信息盒是中文界面文案(出典/科目),题面容器为 lang=ja,这里标回中文取中文字形
    if (rows.length) parts.push('<div class="qd-srcbox" lang="zh-CN">' + rows.join('') + '</div>');
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

  // ---------------------------------------------------------------- 渐进提示(逐层揭示)
  // 初始只显示「提示 1」,点「再看一条」展开下一条,直到全部;每条走渲染管线 + typeset。
  // 用户先想再看,契合开放题自学。内容为空则整块不显示(旧题照常)。
  function renderHints(hints) {
    var wrap = el.hints;
    if (!wrap) return;
    hints = (hints || []).filter(function (h) { return (h || '').trim(); });
    if (!hints.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    wrap.innerHTML =
      '<div class="qd-hints-head"><span class="qd-hints-ic">💡</span>提示 · ヒント</div>' +
      '<div class="qd-hints-list" id="qdHintsList"></div>' +
      '<button type="button" class="qd-hints-more" id="qdHintsMore"></button>';
    var listEl = wrap.querySelector('#qdHintsList');
    var moreBtn = wrap.querySelector('#qdHintsMore');
    var shown = 0;
    function updateBtn() {
      var left = hints.length - shown;
      moreBtn.hidden = left <= 0;
      if (left > 0) moreBtn.textContent = '再看一条(还剩 ' + left + ' 条)';
    }
    function revealNext() {
      if (shown >= hints.length) return;
      var item = document.createElement('div');
      item.className = 'qd-hint';
      var badge = document.createElement('span');
      badge.className = 'qd-hint-n';
      badge.textContent = '提示 ' + (shown + 1);
      var body = document.createElement('div');
      body.className = 'qd-hint-body solbody';
      item.appendChild(badge);
      item.appendChild(body);
      listEl.appendChild(item);
      renderInto(body, hints[shown], 'ja');   // 复用管线(protectMath/renderMarkdown)
      typeset(body);                            // MathJax v4 正确渲染 $公式$
      shown++;
      updateBtn();
    }
    moreBtn.addEventListener('click', revealNext);
    revealNext();   // 初始揭示「提示 1」
  }

  // ---------------------------------------------------------------- 采点结构化题解(四段卡片)
  // 方針=蓝(insight)/ 答案例=橙(brand)/ 失点=红(warn)/ 部分点=绿(conclusion),
  // 复用既有 callout 色板。各段 md 走渲染管线 + typeset;整块空则不显示。
  var STRUCT_SECTIONS = [
    { key: 'houshin', label: '解答方針', kind: 'houshin' },
    { key: 'model',   label: '答案例',   kind: 'model' },
    { key: 'shitten', label: '典型失点', kind: 'shitten' },
    { key: 'haiten',  label: '部分点分布', kind: 'haiten' }
  ];
  function renderStructured(s) {
    var wrap = el.structured;
    if (!wrap) return;
    s = s || {};
    var has = STRUCT_SECTIONS.some(function (sec) { return (s[sec.key] || '').trim(); });
    if (!has) { wrap.hidden = true; return; }
    wrap.hidden = false;
    wrap.innerHTML = '<div class="qd-struct-head">採点ポイント · 采点结构化</div>' +
                     '<div class="qd-struct-grid" id="qdStructGrid"></div>';
    var grid = wrap.querySelector('#qdStructGrid');
    var esc = window.escapeHtml || function (x) { return x; };
    STRUCT_SECTIONS.forEach(function (sec) {
      var raw = (s[sec.key] || '').trim();
      if (!raw) return;
      var card = document.createElement('div');
      card.className = 'qd-struct-card ' + sec.kind;
      card.innerHTML = '<div class="qd-struct-card-h"><span class="qd-struct-bar"></span>' +
                       '<span class="qd-struct-t">' + esc(sec.label) + '</span></div>' +
                       '<div class="qd-struct-b solbody"></div>';
      grid.appendChild(card);
      var body = card.querySelector('.qd-struct-b');
      renderInto(body, raw, 'ja');   // 复用管线
      typeset(body);
    });
  }

  // ---------------------------------------------------------------- 相关题(顺藤摸瓜)
  // 拉 /related,渲染轻量卡片(链到详情页)。纯元信息,无需 MathJax;空则整块隐藏。
  function renderRelated() {
    var wrap = document.getElementById('qdRelated');
    var grid = document.getElementById('qdRelatedGrid');
    if (!wrap || !grid) return;
    apiFetch('/api/questions/' + qid + '/related?limit=6').then(function (resp) {
      var list = (resp.data && resp.data.related) || [];
      if (!list.length) { wrap.hidden = true; return; }
      var esc = window.escapeHtml || function (x) { return x; };
      grid.innerHTML = list.map(function (c) {
        var meta = [];
        if (c.subject) meta.push('<span class="qd-rel-chip subject">' + esc(c.subject) + '</span>');
        if (c.difficulty) meta.push('<span class="qd-rel-chip">' + esc(c.difficulty) + '</span>');
        var shared = (c.shared_tags || []).slice(0, 3).map(function (t) {
          return '<span class="qd-rel-tag">同 · ' + esc(t) + '</span>';
        }).join('');
        return '<a class="qd-rel-card" href="/questions/' + c.id + '">' +
               '<div class="qd-rel-title">' + esc(c.source || ('题目 #' + c.id)) + '</div>' +
               '<div class="qd-rel-meta">' + meta.join('') + '</div>' +
               (shared ? '<div class="qd-rel-tags">' + shared + '</div>' : '') +
               '</a>';
      }).join('');
      wrap.hidden = false;
    }).catch(function () { wrap.hidden = true; });
  }

  // ---------------------------------------------------------------- 我的作答(采点评分)
  var answerFiles = [];   // 待提交 File(≤4)
  function initAnswer() {
    var sec = document.getElementById('qdAnswer');
    if (!sec) return;
    var fileInput = document.getElementById('qdFileInput');
    var pickBtn = document.getElementById('qdPickBtn');
    var submitBtn = document.getElementById('qdSubmitBtn');
    var thumbs = document.getElementById('qdThumbs');

    function renderThumbs() {
      thumbs.innerHTML = '';
      answerFiles.forEach(function (f, i) {
        var cell = document.createElement('div');
        cell.className = 'qd-thumb';
        var img = document.createElement('img');
        img.alt = '作答预览'; img.src = URL.createObjectURL(f);
        var x = document.createElement('button');
        x.type = 'button'; x.className = 'qd-thumb-x'; x.dataset.i = i;
        x.setAttribute('aria-label', '移除'); x.textContent = '×';
        cell.appendChild(img); cell.appendChild(x);
        thumbs.appendChild(cell);
      });
      submitBtn.disabled = answerFiles.length === 0;
    }
    pickBtn.addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () {
      Array.prototype.slice.call(fileInput.files || []).forEach(function (f) {
        if (answerFiles.length < 4) answerFiles.push(f);
      });
      if (answerFiles.length >= 4 && window.showToast) window.showToast('最多 4 张', 'warning');
      fileInput.value = '';
      renderThumbs();
    });
    thumbs.addEventListener('click', function (e) {
      var x = e.target.closest && e.target.closest('.qd-thumb-x');
      if (!x) return;
      answerFiles.splice(Number(x.dataset.i), 1);
      renderThumbs();
    });
    submitBtn.addEventListener('click', function () {
      if (!answerFiles.length) return;
      var grade = document.getElementById('qdGrade');
      submitBtn.disabled = true;
      grade.hidden = false;
      grade.innerHTML = '<div class="qd-grading"><span class="qd-spin"></span>' +
        '批改中…(手写识别与采点可能需十几秒)</div>';
      var fd = new FormData();
      answerFiles.forEach(function (f) { fd.append('images', f); });
      apiFetch('/api/questions/' + qid + '/submissions', { method: 'POST', body: fd })
        .then(function (resp) {
          answerFiles = []; renderThumbs();
          renderGrade(resp.data.submission);
          loadHistory();
        }).catch(function (err) {
          grade.innerHTML = '<div class="qd-grade-err">提交失败:' +
            (window.escapeHtml ? window.escapeHtml(err.message) : err.message) + '</div>';
          submitBtn.disabled = false;
        });
    });
    loadHistory();
  }

  // 渲染一份评分结果:总分环 + 采点逐项进度条 + 作答转写(折叠)+ 综合反馈。
  function renderGrade(sub) {
    var grade = document.getElementById('qdGrade');
    if (!grade || !sub) return;
    var esc = window.escapeHtml || function (x) { return x; };
    grade.hidden = false;
    if (sub.status === 'failed') {
      grade.innerHTML = '<div class="qd-grade-err">批改失败:' + esc(sub.error || '未知错误') + '</div>';
      return;
    }
    var isStub = sub.grader === 'stub';
    var pct = sub.max_score > 0 ? Math.round((sub.total_score / sub.max_score) * 100) : 0;
    var html = '';
    if (isStub) {
      html += '<div class="qd-grade-stub">⚠️ AI 阅卷引擎尚未配置,以下为占位。你的作答已保存,配置后可重新批改。</div>';
    }
    html += '<div class="qd-grade-score">' +
      '<div class="qd-grade-num"><b>' + (sub.total_score != null ? sub.total_score : '—') +
      '</b><span>/ ' + (sub.max_score || 0) + '</span></div>' +
      '<div class="qd-grade-ring" style="--pct:' + pct + '"><span>' + pct + '%</span></div></div>';
    var bd = sub.rubric_breakdown || [];
    if (bd.length) {
      html += '<div class="qd-grade-bd">';
      bd.forEach(function (it) {
        var w = it.max > 0 ? Math.round((it.awarded / it.max) * 100) : 0;
        html += '<div class="qd-bd-item"><div class="qd-bd-top">' +
          '<span class="qd-bd-label">' + esc(it.label) + '</span>' +
          '<span class="qd-bd-pts">' + it.awarded + ' / ' + it.max + '</span></div>' +
          '<div class="qd-bd-bar"><i style="width:' + w + '%"></i></div>' +
          (it.comment ? '<div class="qd-bd-comment">' + esc(it.comment) + '</div>' : '') + '</div>';
      });
      html += '</div>';
    }
    html += '<details class="qd-grade-trans"><summary>我们读到的作答</summary>' +
      '<div class="qd-trans-body solbody" id="qdTransBody"></div></details>';
    html += '<div class="qd-grade-fb"><div class="qd-fb-h">综合反馈</div>' +
      '<div class="qd-fb-body solbody" id="qdFbBody"></div></div>';
    grade.innerHTML = html;
    var tb = document.getElementById('qdTransBody');
    if (tb) { renderInto(tb, sub.transcription || '(无转写)', 'ja'); typeset(tb); }
    var fb = document.getElementById('qdFbBody');
    if (fb) { renderInto(fb, sub.feedback || '', 'ja'); typeset(fb); }
  }

  function loadHistory() {
    var box = document.getElementById('qdSubHistory');
    if (!box) return;
    apiFetch('/api/questions/' + qid + '/submissions').then(function (resp) {
      var subs = (resp.data && resp.data.submissions) || [];
      if (!subs.length) { box.hidden = true; return; }
      var esc = window.escapeHtml || function (x) { return x; };
      box.hidden = false;
      box.innerHTML = '<div class="qd-subhist-h">历史作答(' + subs.length + ')</div>' +
        subs.map(function (s) {
          var score = s.status === 'graded' ? (s.total_score + ' / ' + s.max_score) :
            (s.status === 'failed' ? '失败' : '处理中');
          return '<div class="qd-subhist-row">' +
            '<span class="qd-subhist-date">' + esc(s.created_at || '') + '</span>' +
            '<span class="qd-subhist-score">' + esc(String(score)) + '</span>' +
            '<button type="button" class="qd-subhist-view" data-id="' + s.id + '">查看</button>' +
            '<button type="button" class="qd-subhist-del" data-id="' + s.id + '" aria-label="删除">🗑</button>' +
            '</div>';
        }).join('');
      box.querySelectorAll('.qd-subhist-view').forEach(function (b) {
        b.addEventListener('click', function () {
          var s = subs.filter(function (x) { return x.id === Number(b.dataset.id); })[0];
          if (s) {
            renderGrade(s);
            document.getElementById('qdGrade').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        });
      });
      box.querySelectorAll('.qd-subhist-del').forEach(function (b) {
        b.addEventListener('click', function () {
          apiFetch('/api/submissions/' + b.dataset.id, { method: 'DELETE' })
            .then(function () { loadHistory(); if (window.showToast) window.showToast('已删除', 'success'); })
            .catch(function (e) { if (window.showToast) window.showToast(e.message, 'danger'); });
        });
      });
    }).catch(function () { box.hidden = true; });
  }

  // ---------------------------------------------------------------- 收藏 + 笔记
  function initBookmark() {
    var btn = document.getElementById('qdBookmark');
    if (!btn) return;
    function paint(on) {
      btn.textContent = on ? '★' : '☆';
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', String(on));
      btn.title = on ? '已收藏(点击取消)' : '收藏';
    }
    apiFetch('/api/questions/' + qid + '/bookmark')
      .then(function (r) { paint(!!(r.data && r.data.bookmarked)); }).catch(function () {});
    btn.addEventListener('click', function () {
      apiFetch('/api/questions/' + qid + '/bookmark', { method: 'POST' })
        .then(function (r) {
          var on = !!(r.data && r.data.bookmarked);
          paint(on);
          if (window.showToast) window.showToast(on ? '已收藏' : '已取消收藏', 'success');
        }).catch(function (e) { if (window.showToast) window.showToast(e.message, 'danger'); });
    });
  }

  function initNotes() {
    var ta = document.getElementById('qdNoteText');
    var status = document.getElementById('qdNoteStatus');
    if (!ta) return;
    apiFetch('/api/questions/' + qid + '/note')
      .then(function (r) { ta.value = (r.data && r.data.content) || ''; }).catch(function () {});
    var t = null, dirty = false;
    function save() {
      if (status) status.textContent = '保存中…';
      apiFetch('/api/questions/' + qid + '/note', { method: 'PUT', body: { content: ta.value } })
        .then(function () {
          dirty = false;
          if (status) { status.textContent = '已保存 ✓'; setTimeout(function () { status.textContent = ''; }, 1500); }
        }).catch(function () { if (status) status.textContent = '保存失败'; });
    }
    ta.addEventListener('input', function () {
      dirty = true;
      if (status) status.textContent = '编辑中…';
      clearTimeout(t); t = setTimeout(save, 800);
    });
    ta.addEventListener('blur', function () { if (dirty) { clearTimeout(t); save(); } });
  }

  // ---------------------------------------------------------------- 装载
  function load() {
    apiFetch('/api/questions/' + qid).then(function (resp) {
      var q = resp.data.question;

      el.title.textContent = q.source || ('题目 #' + q.id);
      el.chips.innerHTML = chipsHtml(q);
      el.problem.innerHTML = problemHtml(q);
      typeset(el.problem);
      renderHints(q.hints);                   // 渐进提示(逐层揭示,惰性)
      initMastery();   // 回填并高亮当前掌握状态
      renderRelated(); // 相关题(独立异步拉取,不阻塞正文)
      initAnswer();    // 我的作答:上传批改 + 历史(独立异步)
      initBookmark();  // 收藏星标
      initNotes();     // 私人笔记(自动保存)

      renderStructured(q.solution_structured); // 采点四段(惰性)
      var ja = (q.solution_ja || '').trim();
      var zh = (q.solution_latex || '').trim();
      renderInto(el.trackJa, ja, 'ja');
      renderInto(el.trackZh, zh, 'zh');

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
