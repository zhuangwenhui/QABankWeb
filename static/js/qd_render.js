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
  function cph(i) { return 'QDCODEPLACEHOLDER' + i + 'ENDQD'; }

  function fixTextModeEscapes(tex) { return tex; }

  function protectMath(src) {
    var store = [];
    function grab(m) { store.push(fixTextModeEscapes(m)); return ph(store.length - 1); }

    // 先把代码段挡开:代码里的 $ 不是数学。少了这一步,`)$` 这种代码段里的美元号会跟
    // 后面真正的公式配上对,把中间整段正文吞进"公式"里 —— 页面上表现为文字被拆成
    // 一行一个字的碎片(id=266「以 `)$` 收」即此)。挡开后原样放回,仍由 markdown-it
    // 正常渲染成 <code>。
    var code = [];
    src = src.replace(/```[\s\S]*?```|`[^`\n]*`/g, function (m) {
      code.push(m);
      return cph(code.length - 1);
    });

    // `\$` 是**字面美元号**,不能充当定界符。少了 (?<!\\) 这个判断,`$(L)\$$` 里
    // 「\$ 的 $ + 收尾的 $」会被当成一对 display 定界符,于是从那里到下一个 \$ 之间
    // 的整段正文都被吞进"公式",页面上表现为文字碎成一行一个字(id=266 即此)。
    src = src.replace(/(?<!\\)\$\$([\s\S]+?)(?<!\\)\$\$/g, grab);   // 先 display
    src = src.replace(/(?<!\\)\$((?:\\.|[^\$\\\n])+?)\$/g, grab);   // 再 inline

    code.forEach(function (m, i) { src = src.split(cph(i)).join(m); });
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

  // ---------------------------------------------------------------- MathJax 排版
  // 两次线上事故的结论都落在这里,改动前请读完:
  //   1) 题解整篇停在 LaTeX 源码态 —— 真因是 CSP 挡掉了 MathJax v4 的 blob Worker,
  //      导致其 Promise 未处理地 reject、startup/typesetPromise 永久挂起。已在 app.py
  //      补 worker-src/child-src 'self' blob:。
  //   2) 题面区空白 —— 曾为绕开 (1) 写过"同步排版 + 促发重试"的兜底,它会与自己促发的
  //      异步排版并发作用于同一批文本节点,MathJax 抛 splitText offset 错。病根既除,
  //      兜底即删,改为**串行的纯 Promise**。
  // 因此:排版只走 typesetPromise,且全页共用一条串行队列,永不并发。
  // 只防死锁。重页面(一页几百个公式)在慢网下整页重排本来就要十几秒,超时定得太紧
  // 只会误报并提前放弃。
  var TYPESET_TIMEOUT_MS = 45000;
  var chain = Promise.resolve();    // 全页共用的串行排版队列

  /**
   * 等到可以安全排版为止。
   *
   * 两个条件缺一不可:①typesetPromise 已存在;②MathJax 自身启动完成(startup.promise)。
   * 只等 ① 就动手,会和 MathJax 的开场自动排版抢同一批文本节点,那次调用便一直不 settle
   * ——实测首块要卡满 20s 超时,整页公式在近 20 秒里都是源码态。
   * startup.promise 兜一层超时:万一它又因某种原因不 settle,也只慢一次,不至于全站没数学。
   */
  // startup.promise 实测常常不 settle(它是 MathJax 的滚动队列头,被任一未完成操作占住),
  // 所以只给它很短的礼让时间,别让整页公式为它干等。
  var STARTUP_WAIT_MS = 1500;
  function mathReady(maxWaitMs) {
    var deadline = Date.now() + (maxWaitMs || 20000);
    return new Promise(function (res) {
      (function poll() {
        var MJ = window.MathJax;
        if (MJ && MJ.typesetPromise) {
          var sp = MJ.startup && MJ.startup.promise;
          if (!sp) return res(true);
          return Promise.race([
            sp.then(function () { return true; }, function () { return true; }),
            new Promise(function (r) { setTimeout(function () { r(true); }, STARTUP_WAIT_MS); })
          ]).then(res);
        }
        if (Date.now() > deadline) return res(false);
        setTimeout(poll, 50);
      })();
    });
  }

  /**
   * 排版前必须先清掉 MathJax 对该节点的旧记录。
   *
   * 我们是把 innerHTML 整块换掉来更新内容的,MathJax 文档对象里却还留着上一轮的 MathItem,
   * 它们指向已被替换的文本节点。再排版时 MathJax 按旧偏移去 splitText,于是抛
   *   IndexSizeError: The offset N is larger than the Text node's length
   * 该次 Promise 未处理地 reject,整块公式停在源码态 —— 这正是 2026-07-26 题面区空白的机制。
   * 官方对动态内容的要求就是 typesetClear 之后再 typeset,我们此前从未调过。
   */
  function clearNode(node) {
    var MJ = window.MathJax;
    try {
      if (MJ && MJ.typesetClear) MJ.typesetClear([node]);
    } catch (e) { /* 清理失败不该阻断渲染 */ }
  }

  /**
   * 排版:短时间内的多次请求合并成**一次整页排版**(typesetClear() + typesetPromise())。
   *
   * 逐块 typesetPromise([node]) 试过三种写法,都不可靠:同一页里往往只有第一块排得出来,
   * 其余的调用要么不 settle、要么抛 IndexSizeError(splitText 偏移),而且每次运行失败的
   * 块还不一样。MathJax 本就是按整篇文档设计的 —— 先 typesetClear() 丢掉全部旧 MathItem
   * (我们整块替换 innerHTML,旧记录必然失效),再整页重排,结果稳定。
   * 防抖把详情页那十几次调用收敛成一两次;配合 base.html 关掉开场自动排版,
   * 全站排版有且只有这一条串行路径。
   */
  var DEBOUNCE_MS = 180;
  var pendingTimer = null;
  var pendingResolvers = [];

  function typesetAll() {
    var MJ = window.MathJax;
    if (!MJ || !MJ.typesetPromise) return Promise.resolve();
    try {
      if (MJ.typesetClear) MJ.typesetClear();
    } catch (e) { /* 清理失败不该阻断渲染 */ }
    return new Promise(function (done) {
      var t = setTimeout(function () {
        console.warn('MathJax 排版超时');
        done();
      }, TYPESET_TIMEOUT_MS);
      MJ.typesetPromise().then(
        function () { clearTimeout(t); done(); },
        function (e) { clearTimeout(t); console.warn('MathJax 排版失败:', e); done(); });
    });
  }

  function flush() {
    pendingTimer = null;
    var waiting = pendingResolvers;
    pendingResolvers = [];
    chain = chain.then(function () {
      return mathReady().then(function (ok) {
        if (!ok) { console.warn('MathJax 未就绪,公式保持源码'); return; }
        return typesetAll();
      });
    }).catch(function (e) {
      console.warn('MathJax 排版链异常:', e);
    }).then(function () { waiting.forEach(function (r) { r(); }); });
    return chain;
  }

  /** 请求排版(节点参数保留以兼容调用方,实际按整页合并处理)。 */
  function typeset(node) {   // eslint-disable-line no-unused-vars
    return new Promise(function (res) {
      pendingResolvers.push(res);
      if (pendingTimer) clearTimeout(pendingTimer);
      pendingTimer = setTimeout(flush, DEBOUNCE_MS);
    });
  }

  /**
   * 从题解里切出开头的「問題重述」段。
   *
   * 126 道采集题因转载条件不放原题面,question_latex 只是一句声明,真正的题目写在
   * 题解开头的 `## 問題重述` 里 —— 于是「想看题目就必须先看答案」,做题这件事直接没了。
   * 这里把它切出来还给题面区,并从题解正文中移除以免重复。
   * 返回 {restatement, body};题解不以重述开头时原样返回。
   */
  var RESTATE_RE = /^##[ \t]*(問題重述|题目重述|問題文)[ \t]*$/m;
  function splitRestatement(mdSrc) {
    var src = mdSrc || '';
    var m = RESTATE_RE.exec(src);
    if (!m || m.index > 60) return { restatement: '', body: src };
    var rest = src.slice(m.index + m[0].length);
    var next = /^##[ \t]+/m.exec(rest);
    return {
      restatement: (next ? rest.slice(0, next.index) : rest).trim(),
      body: (next ? rest.slice(next.index) : '').trim()
    };
  }

  /**
   * 列表/卡片预览该用哪段文字。
   *
   * 转载条件下 question_latex 只是一句版权声明(还带一条 URL),直接拿来当预览,
   * 卡片上就是一行网址而不是题目 —— 与其它卡片风格也不统一。有「問題重述」时优先用它;
   * 退化时也把裸 URL 去掉,预览格里不该出现链接。
   */
  // 转载声明式题面:正文没放出来,只有一句版权说明(常带一条官方存档 URL)
  var NOTICE_RE = /(転載|掲載しません|公式アーカイブ|原題面)/;

  /** question_latex 是否只是版权声明而无实质题面。 */
  function isNoticeOnly(text) {
    var t = String(text || '');
    if (!t.trim()) return true;
    if (!NOTICE_RE.test(t)) return false;
    // 去掉数学与空白后仍很短 → 确实没有正文
    return t.replace(/\$\$[\s\S]+?\$\$/g, '').replace(/\$[^$\n]+\$/g, '')
             .replace(/\s/g, '').length < 220;
  }

  /**
   * 这道题的题面正文该取哪一段。
   *
   * 只有当 question_latex 确实只是版权声明时,才改用题解开头的「問題重述」;
   * 题面本身有正文却也拼上重述,页面上就会**把同一道题显示两遍**(实测会影响 197 道题)。
   */
  function questionText(q) {
    q = q || {};
    var own = q.question_latex || '';
    if (!isNoticeOnly(own)) return own;
    return splitRestatement(q.solution_ja || '').restatement || own;
  }

  function previewSource(q) {
    return questionText(q)
      .replace(/https?:\/\/\S+/g, '').replace(/[（(]\s*[)）]/g, '').trim();
  }

  /**
   * 列表/卡片里的预览格:先截断再渲染。
   *
   * 预览在视觉上被 CSS 裁到几行,但整篇题面照样会被 markdown 渲染并交给 MathJax ——
   * 一页 20 题实测排了 1820 个公式,大部分根本看不见,列表因此要等十几秒才排完。
   * 按字符数截到段落边界,渲染量降一个量级,可见部分完全不变。
   */
  function renderPreviewInto(node, raw, track, maxChars) {
    var limit = maxChars || 240;
    var text = String(raw || '');
    if (text.length > limit) {
      var cut = text.slice(0, limit);
      var nl = cut.lastIndexOf('\n');
      text = (nl > limit * 0.5 ? cut.slice(0, nl) : cut) + '\n\n…';
    }
    node.classList.add('qd-preview');
    renderInto(node, text, track);
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

  // 假名 = 日语的判据(汉字两语共用,判不出来)
  var KANA_RE = /[぀-ゟ゠-ヿ]/;

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
      // 区块小标题是日语的采点术语,但正文实际上几乎全是中文(全库 358 道里 357 道如此)。
      // 一律按 'ja' 渲染会让容器标题(Note/注意/結論)和字体走日文轨 —— 中文正文吃日文
      // 字形正是之前被指出的那类问题。按有没有假名判定,内容是哪种语言就按哪种渲染。
      renderMd(raw, KANA_RE.test(raw) ? 'ja' : 'zh', card.querySelector('.qd-struct-b'));
    });
  }

  window.QDRender = {
    LABELS: LABELS,
    PURIFY_CFG: PURIFY_CFG,
    renderMarkdown: renderMarkdown,
    renderInto: renderInto,
    renderPreviewInto: renderPreviewInto,
    splitRestatement: splitRestatement,
    previewSource: previewSource,
    questionText: questionText,
    isNoticeOnly: isNoticeOnly,
    renderMd: renderMd,
    typeset: typeset,
    mathReady: mathReady,
    enhanceSteps: enhanceSteps,
    STRUCT_SECTIONS: STRUCT_SECTIONS,
    renderStructuredInto: renderStructuredInto
  };
})();
