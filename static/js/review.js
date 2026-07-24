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
    if ((q.question_latex || '').trim()) renderMd(q.question_latex, 'ja', probEl);
    else probEl.innerHTML = '<p class="rv-empty">(无题目内容)</p>';

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
