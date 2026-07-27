/**
 * 间隔复习页:到期错题逐题揭示题解 + 四键自评(SM-2 排期)。
 *
 * 依赖:
 *   - utils.js:apiFetch / escapeHtml / showToast(全站已加载)
 *   - qd_render.js:window.QDRender 共享渲染管线(renderMd / renderStructuredInto)
 *   - markdown-it / markdown-it-container / DOMPurify(模板自托管加载)
 *   - MathJax v4(base.html 已加载,tex-svg)
 *
 * 渲染管线不再自持副本,统一复用 qd_render.js(与详情页同一实现,杜绝漂移)。
 */
(function () {
  'use strict';

  var appEl = document.getElementById('rvApp');
  if (!appEl) return;

  // 渲染管线共享自 qd_render.js(此前为 question_detail.js 的自包含副本,已抽出统一)。
  var R = window.QDRender || {};
  var renderMd = R.renderMd;
  var renderStructuredInto = R.renderStructuredInto;

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

  /** 题目元信息小标签(科目/难度/出典/章节/自由标签)。与详情页同一套 .qd-chip 样式。 */
  function chipsHtml(q) {
    var out = [];
    if (q.subject) out.push('<span class="qd-chip subject">' + esc(q.subject) + '</span>');
    if (q.difficulty) out.push('<span class="qd-chip diff">难度 ' + esc(q.difficulty) + '</span>');
    if (q.source) out.push('<span class="qd-chip"><span class="k">出典</span>' + esc(q.source) + '</span>');
    if (q.chapter) out.push('<span class="qd-chip">' + esc(q.chapter) + '</span>');
    (q.tags || []).forEach(function (t) { out.push('<span class="qd-chip">' + esc(t) + '</span>'); });
    return out.join('');
  }

  /** 刷新顶部进度:第几题 / 共几题 + 进度条。按 pos 而非 reviewedCount —— 跳过也算走过。 */
  function updateProgress() {
    el.progress.hidden = false;
    el.bar.hidden = false;
    el.index.textContent = Math.min(pos + 1, queue.length);
    el.total.textContent = queue.length;
    var pct = queue.length ? (pos / queue.length) * 100 : 0;
    el.barFill.style.width = pct.toFixed(1) + '%';
  }

  /**
   * 收尾态。文案分两种:本次评过题的说「本次复习完成」,一进来就没题的说「今日复习完成」——
   * 后者容易被误当成「页面坏了」,所以补一句「去做点新题吧」。
   */
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

  /**
   * 渲染一张复习卡:先只出题面(揭示前),点"显示答案"后再出题解。
   *
   * ⚠️ 本函数把「题面区要不要用問題重述」这个判定**算了两遍**:
   *   · 下面第一处(pre)决定**题解正文**要不要把重述剪掉;
   *   · 后面第二处(noticeOnly / split)决定**题面区**显示什么。
   * 两处必须同进同退。不一致的后果是二选一:重述被显示两遍(题面一次、题解一次),
   * 或者揭示前题面区空着、学生根本看不到题目。
   *
   * 判定本身还有第三份在 static/js/question_detail.js(详情页),三处口径必须一致。
   * 之所以没抽成一个函数:三处各自要的返回值不同(有的要 body、有的要 restatement、
   * 有的两个都要),抽出来会变成一个带 flag 的四不像。合并留给 V2.0 连同复习页重做一起处理。
   */
  function renderCard(entry) {
    var q = entry.question || {};
    var jaFull = (q.solution_ja || '').trim();
    var zh = (q.solution_latex || '').trim();
    // 判定其一(决定题解正文):题面区会显示「問題重述」时,题解里就去掉它以免重复
    var pre = (window.QDRender && window.QDRender.isNoticeOnly(q.question_latex))
      ? window.QDRender.splitRestatement(jaFull) : { restatement: '', body: jaFull };
    var ja = pre.restatement ? pre.body : jaFull;
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
          '<div class="qd-structured" id="rvStructured" hidden></div>' +
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
    // 判定其二(决定题面区):转载题的题面在题解开头的「問題重述」里 —— 复习页要把它还给题面,
    // 否则揭示答案前学生根本看不到题目。
    // ⚠️ 这里的条件必须与本函数开头那处(变量 pre)完全一致,理由见函数上方说明。
    var R2 = window.QDRender;
    var noticeOnly = R2 ? R2.isNoticeOnly(q.question_latex) : !(q.question_latex || '').trim();
    var split = (noticeOnly && R2) ? R2.splitRestatement(q.solution_ja || '')
                                   : { restatement: '', body: '' };
    var qtext = (q.question_latex || '').trim();
    if (split.restatement) {
      renderMd((qtext ? qtext + '\n\n' : '') + split.restatement, 'ja', probEl);
    } else if (qtext) {
      renderMd(qtext, 'ja', probEl);
    } else {
      probEl.innerHTML = '<p class="rv-empty">(无题目内容)</p>';
    }

    var revealWrap = document.getElementById('rvRevealWrap');
    var solWrap = document.getElementById('rvSolWrap');
    document.getElementById('rvReveal').addEventListener('click', function () {
      revealWrap.hidden = true;
      solWrap.hidden = false;
      renderStructuredInto(document.getElementById('rvStructured'), q.solution_structured);
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

  /**
   * 提交本题自评,成功后前进到下一题。
   *
   * 失败时把评分按钮**复原为可点**并提示重试 —— 排期没落库就前进的话,这题下次还会到期,
   * 但学生以为已经评过了。
   */
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

  /** 前进到下一题;队列走完则显示收尾态。每题回到页首,免得停在上一题的滚动位置。 */
  function next() {
    if (pos >= queue.length) { showDone(); return; }
    renderCard(queue[pos]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /**
   * 拉取到期队列(最多 20 题)并渲染第一题。
   *
   * 过滤掉 question 为空的条目:题目被删但错题本记录还在时会出现这种孤儿行,
   * 不滤会在 renderCard 里抛异常、整页白屏。
   */
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
