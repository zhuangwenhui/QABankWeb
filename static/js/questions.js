/**
 * 题目管理页脚本(templates/questions.html)。
 *
 * 依赖:utils.js(apiFetch/buildQuery/escapeHtml/debounce/typesetMath/
 *       difficultyBadge/tagBadges/formatDate)、toast.js(showToast)、
 *       Bootstrap 5、CodeMirror 5.65.2(stex 模式,CDN 加载失败时降级为纯文本)。
 *
 * 分区目录:
 *   1. 常量与页面状态
 *   2. DOM 引用与初始化
 *   3. 事件绑定
 *   4. 视图切换(localStorage 记忆)
 *   5. 筛选与高级搜索
 *   6. 搜索历史与筛选预设(localStorage)
 *   7. 数据加载与渲染(表格/卡片/分页)
 *   8. 选择与批量操作
 *   9. 书签(错题本 add/remove/check_batch)
 *  10. 题目详情 Modal
 *  11. 右键上下文菜单
 *  12. 新建/编辑 Modal(CodeMirror + 实时预览 + 判重 + 图片上传)
 *  13. 通用小工具
 */
(function () {
  'use strict';

  /* ============================================================ 1. 常量与页面状态 */

  const CFG = window.PAGE_CONFIG || { subjects: [], difficulties: [], perPageOptions: [10, 20, 50, 100] };

  const LS_KEYS = {
    viewMode: 'qb.questions.viewMode',
    history: 'qb.questions.searchHistory',
    presets: 'qb.questions.presets',
  };
  const HISTORY_LIMIT = 20;

  const FILTER_LABELS = {
    school: '院校', major: '専攻', year: '年份', subjectGroup: '学科',
    subject: '科目', chapter: '章节', difficulty: '难度', masteryStatus: '掌握状态', source: '出处',
    search: '关键词', questionId: 'ID', tagFilter: '标签', dateFrom: '入库从', dateTo: '入库至',
  };

  const state = {
    page: 1,
    perPage: 20,
    total: 0,
    pages: 1,
    questions: [],              // 当前页题目
    selected: new Set(),        // 跨页保留的选中题目 id
    bookmarked: new Set(),      // 已在错题本中的题目 id(当前已知)
    mastery: new Map(),         // 掌握状态回填:qid → 'done' | 'mastered'(无键=未做)
    viewMode: 'table',          // 'table' | 'card'
    editingId: null,            // 正在编辑的题目 id(null = 新建)
    editImages: { question_image: null, solution_image: null },
    tempUploads: new Set(),     // 本次编辑会话新上传、尚未保存的临时文件名
    editSaved: false,           // 本次编辑是否已成功保存(决定关窗时是否清理临时文件)
    contextTargetId: null,      // 右键菜单目标题目 id
    detailId: null,             // 详情 Modal 当前题目 id
  };

  const editors = { question: null, solution: null }; // CodeMirror 实例
  let editorsInitialized = false;
  let loadSeq = 0;    // 列表加载请求序号:仅渲染最新一次响应,防止旧响应覆盖新结果
  const modals = {};  // Bootstrap Modal 实例
  const el = {};      // DOM 引用集合

  /* ============================================================ 2. DOM 引用与初始化 */

  /** 收集页面 DOM 引用 */
  function cacheDom() {
    const ids = [
      'btnViewTable', 'btnViewCard', 'checkAllPage', 'checkAll',
      'historyMenu', 'btnPresetDropdown', 'presetNameInput', 'btnSavePreset', 'presetList',
      'btnNewQuestion', 'filterSubject', 'filterChapter', 'filterDifficulty',
      'filterMastery', 'filterSchool', 'filterMajor', 'filterYear', 'filterSubjectGroup',
      'filterSource', 'filterSearch', 'sourceOptions', 'editChapterOptions',
      'advancedPanel', 'advQuestionId', 'advTags', 'advDateFrom', 'advDateTo',
      'btnAdvSearch', 'btnAdvReset',
      'batchToolbar', 'batchCount', 'btnBatchDelete', 'btnBatchTags',
      'btnBatchSource', 'btnBatchErrorBook', 'btnBatchCancel',
      'tableView', 'questionTbody', 'cardView',
      'resultSummary', 'perPageSelect', 'paginationList',
      'detailModal', 'detailQid', 'detailInfo', 'detailQuestionLatex',
      'detailQuestionImage', 'btnToggleSolution', 'detailSolutionWrap',
      'detailSolutionLatex', 'detailSolutionImage', 'btnDetailBookmark', 'btnDetailEdit',
      'editModal', 'editModalTitle', 'editSubject', 'editChapter', 'editDifficulty',
      'editSource', 'sourceHint', 'editTags', 'editQuestionLatex', 'editSolutionLatex',
      'previewQuestion', 'previewSolution', 'fileQuestionImage', 'fileSolutionImage',
      'questionImagePreview', 'solutionImagePreview', 'btnSaveQuestion',
      'batchTagsModal', 'batchTagsCount', 'batchTagsInput', 'btnConfirmBatchTags',
      'batchSourceModal', 'batchSourceCount', 'batchSourceInput', 'btnConfirmBatchSource',
      'contextMenu', 'ctxBookmarkText',
    ];
    ids.forEach((id) => { el[id] = document.getElementById(id); });
  }

  /** 创建 Bootstrap Modal 实例 */
  function initModals() {
    modals.detail = new bootstrap.Modal(el.detailModal);
    modals.edit = new bootstrap.Modal(el.editModal);
    modals.batchTags = new bootstrap.Modal(el.batchTagsModal);
    modals.batchSource = new bootstrap.Modal(el.batchSourceModal);
  }

  /** 页面入口 */
  async function init() {
    cacheDom();
    initModals();
    restoreViewMode();
    bindEvents();
    renderHistoryMenu();
    renderPresetList();
    await loadChapterOptions('');
    await loadFacets();
    initProgressPanel();  // 顶部进度面板:与列表加载并行,失败静默降级,不阻塞
    await loadQuestions({ record: false });
  }

  document.addEventListener('DOMContentLoaded', init);

  /* ============================================================ 2b. 顶部学习进度面板 */

  const PP_LS_COLLAPSED = 'qb_progress_collapsed';

  /** 计数 → 热力图档位(5 档:0 / 1-2 / 3-4 / 5-6 / 7+) */
  function ppHeatLevel(count) {
    if (count <= 0) return 0;
    if (count <= 2) return 1;
    if (count <= 4) return 2;
    if (count <= 6) return 3;
    return 4;
  }

  /** 按预设顺序排列分组键,预设外的键(如后端新增学科)追加在后 */
  function ppOrderedKeys(dataObj, presetOrder) {
    const keys = [];
    (presetOrder || []).forEach((k) => { if (k in dataObj) keys.push(k); });
    Object.keys(dataObj).forEach((k) => { if (!keys.includes(k)) keys.push(k); });
    return keys;
  }

  /** 一组分组进度条(已掌握/总)HTML */
  function ppGroupHtml(title, dataObj, presetOrder) {
    dataObj = dataObj || {};
    const rows = ppOrderedKeys(dataObj, presetOrder).map((k) => {
      const v = dataObj[k] || {};
      const total = v.total || 0;
      const mastered = v.mastered || 0;
      const pct = total ? Math.round((mastered / total) * 100) : 0;
      return `
        <div class="pp-bar-row">
          <span class="pp-bar-label" title="${escapeHtml(k)}">${escapeHtml(k)}</span>
          <span class="pp-bar-track"><span class="pp-bar-fill" style="width:${pct}%"></span></span>
          <span class="pp-bar-num">${mastered}/${total}</span>
        </div>`;
    }).join('');
    return `<div class="pp-group-title">${escapeHtml(title)}</div>${rows}`;
  }

  /** 渲染一行总进度摘要 + 待复习链接 */
  function ppRenderSummary(summary, stats) {
    const box = document.getElementById('ppSummary');
    if (!box) return;
    const o = (summary && summary.overall) || { total: 0, done: 0, mastered: 0 };
    const total = o.total || 0;
    const mastered = o.mastered || 0;
    const pct = total ? Math.round((mastered / total) * 100) : 0;
    const due = stats ? (stats.due_today || 0) : 0;
    const dueCls = due > 0 ? '' : ' is-empty';
    box.innerHTML =
      `<span class="pp-stat">已掌握 <strong>${mastered}</strong> / 总 ${total} <span class="pp-pct">(${pct}%)</span></span>` +
      `<a class="pp-due${dueCls}" href="/review">今日待复习 <strong>${due}</strong></a>`;
  }

  /** 渲染难度/学科两组进度条 */
  function ppRenderGroups(summary) {
    const diffEl = document.getElementById('ppByDifficulty');
    const subjEl = document.getElementById('ppBySubject');
    if (diffEl) diffEl.innerHTML = ppGroupHtml('难度', summary.by_difficulty, CFG.difficulties);
    if (subjEl) subjEl.innerHTML = ppGroupHtml('学科', summary.by_subject, CFG.subjects);
  }

  /** 渲染 GitHub 式做题日历热力图(7 行=周几 × ~53 列=周) */
  function ppRenderHeatmap(calendar) {
    const grid = document.getElementById('ppCalGrid');
    if (!grid) return;
    const cells = [];
    if (calendar.length) {
      // 首日之前补占位格,使首日落在正确的周几行(周日=0 为首行)
      const p = calendar[0].date.split('-').map(Number);
      const firstWeekday = new Date(p[0], p[1] - 1, p[2]).getDay();
      for (let i = 0; i < firstWeekday; i++) {
        cells.push('<span class="pp-cell pp-cell-empty" aria-hidden="true"></span>');
      }
    }
    calendar.forEach((d) => {
      const count = d.count || 0;
      cells.push(
        `<span class="pp-cell l${ppHeatLevel(count)}" title="${escapeHtml(d.date)} · ${count} 题"></span>`);
    });
    grid.innerHTML = cells.join('');

    const legend = document.getElementById('ppCalLegend');
    if (legend) {
      legend.innerHTML = '<span class="pp-legend-label">少</span>' +
        [0, 1, 2, 3, 4].map((l) => `<span class="pp-cell l${l}"></span>`).join('') +
        '<span class="pp-legend-label">多</span>';
    }
  }

  /** 顶部进度面板入口:恢复折叠态、并发拉三接口、分块渲染,失败静默降级。 */
  async function initProgressPanel() {
    const panel = document.getElementById('progressPanel');
    if (!panel) return;
    const toggle = document.getElementById('ppToggle');

    const applyCollapsed = (collapsed) => {
      panel.classList.toggle('is-collapsed', collapsed);
      if (toggle) toggle.setAttribute('aria-expanded', String(!collapsed));
    };
    let collapsed = false;
    try { collapsed = localStorage.getItem(PP_LS_COLLAPSED) === '1'; } catch (e) { /* 无痕模式忽略 */ }
    applyCollapsed(collapsed);
    if (toggle) {
      toggle.addEventListener('click', () => {
        const next = !panel.classList.contains('is-collapsed');
        applyCollapsed(next);
        try { localStorage.setItem(PP_LS_COLLAPSED, next ? '1' : '0'); } catch (e) { /* 忽略 */ }
      });
    }

    const [summaryRes, calRes, statsRes] = await Promise.allSettled([
      apiFetch('/api/progress/summary'),
      apiFetch('/api/progress/calendar?days=365'),
      apiFetch('/api/review/stats'),
    ]);

    const summary = summaryRes.status === 'fulfilled' ? summaryRes.value.data : null;
    const stats = statsRes.status === 'fulfilled' ? statsRes.value.data : null;
    const calendar = calRes.status === 'fulfilled' ? (calRes.value.data.calendar || []) : null;

    let shown = false;
    if (summary) { ppRenderSummary(summary, stats); ppRenderGroups(summary); shown = true; }
    if (calendar) { ppRenderHeatmap(calendar); shown = true; }
    if (shown) panel.hidden = false;  // 三接口全挂则保持隐藏,不打扰列表
  }

  /* ============================================================ 3. 事件绑定 */

  function bindEvents() {
    // ---- 视图切换
    el.btnViewTable.addEventListener('click', () => setViewMode('table'));
    el.btnViewCard.addEventListener('click', () => setViewMode('card'));

    // ---- 基础筛选:变更即刷新(关键词/来源 debounce 400ms)
    el.filterSubject.addEventListener('change', async () => {
      await loadChapterOptions('');
      resetAndLoad();
    });
    el.filterChapter.addEventListener('change', resetAndLoad);
    el.filterDifficulty.addEventListener('change', resetAndLoad);
    el.filterMastery.addEventListener('change', resetAndLoad);

    // 院試定位:院校变→重建専攻级联;任一变更→高亮 + 重新加载
    el.filterSchool.addEventListener('change', () => {
      populateMajors(el.filterSchool.value);
      markLocatorActive();
      resetAndLoad();
    });
    [el.filterMajor, el.filterYear, el.filterSubjectGroup].forEach((sel) => {
      sel.addEventListener('change', () => { markLocatorActive(); resetAndLoad(); });
    });
    // 文本框输入过程中只实时加载,不写历史(避免把「线」「线性」等中间态挤入历史);
    // 仅在明确的搜索动作(失焦 / 回车)时写入一次搜索历史。
    el.filterSource.addEventListener('input', debounce(() => resetAndLoad({ record: false }), 400));
    el.filterSearch.addEventListener('input', debounce(() => resetAndLoad({ record: false }), 400));
    [el.filterSource, el.filterSearch].forEach((input) => {
      input.addEventListener('blur', () => recordHistory(collectFilters()));
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); recordHistory(collectFilters()); }
      });
    });

    // ---- 高级搜索
    el.btnAdvSearch.addEventListener('click', resetAndLoad);
    el.btnAdvReset.addEventListener('click', async () => {
      await applyFilterState({});
      loadQuestions({ record: false });
    });

    // ---- 搜索历史 / 预设
    el.historyMenu.addEventListener('click', onHistoryMenuClick);
    el.btnSavePreset.addEventListener('click', saveCurrentPreset);
    el.presetNameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); saveCurrentPreset(); }
    });
    el.presetList.addEventListener('click', onPresetListClick);

    // ---- 分页
    el.paginationList.addEventListener('click', onPaginationClick);
    el.perPageSelect.addEventListener('change', () => {
      state.perPage = parseInt(el.perPageSelect.value, 10) || 20;
      state.page = 1;
      loadQuestions({ record: false });
    });

    // ---- 列表交互(事件委托)
    el.questionTbody.addEventListener('click', onListClick);
    el.cardView.addEventListener('click', onListClick);
    el.questionTbody.addEventListener('contextmenu', onListContextMenu);
    el.cardView.addEventListener('contextmenu', onListContextMenu);

    // ---- 全选
    el.checkAll.addEventListener('change', () => selectAllCurrentPage(el.checkAll.checked));
    el.checkAllPage.addEventListener('change', () => selectAllCurrentPage(el.checkAllPage.checked));

    // ---- 批量操作
    el.btnBatchDelete.addEventListener('click', batchDelete);
    el.btnBatchTags.addEventListener('click', openBatchTagsModal);
    el.btnBatchSource.addEventListener('click', openBatchSourceModal);
    el.btnBatchErrorBook.addEventListener('click', batchAddErrorBook);
    el.btnBatchCancel.addEventListener('click', clearSelection);
    el.btnConfirmBatchTags.addEventListener('click', confirmBatchTags);
    el.btnConfirmBatchSource.addEventListener('click', confirmBatchSource);

    // ---- 详情 Modal
    el.btnToggleSolution.addEventListener('click', toggleDetailSolution);
    el.btnDetailBookmark.addEventListener('click', () => {
      if (state.detailId != null) toggleBookmark(state.detailId);
    });
    el.btnDetailEdit.addEventListener('click', () => {
      if (state.detailId == null) return;
      modals.detail.hide();
      startEdit(state.detailId);
    });

    // ---- 新建/编辑 Modal
    el.btnNewQuestion.addEventListener('click', () => openEditModal(null));
    el.btnSaveQuestion.addEventListener('click', saveQuestion);
    el.editSource.addEventListener('blur', checkSourceExists);
    el.editSubject.addEventListener('change', updateEditChapterOptions);
    el.fileQuestionImage.addEventListener('change', () => handleImageUpload('question_image', el.fileQuestionImage));
    el.fileSolutionImage.addEventListener('change', () => handleImageUpload('solution_image', el.fileSolutionImage));
    el.editModal.addEventListener('click', (e) => {
      const btn = e.target.closest('.js-remove-image');
      if (btn) removeEditImage(btn.dataset.kind);
    });
    el.editModal.addEventListener('shown.bs.modal', () => {
      // CodeMirror 在隐藏容器内初始化后需要 refresh 才能正确排版
      if (editors.question) editors.question.refresh();
      if (editors.solution) editors.solution.refresh();
      updatePreview('question');
      updatePreview('solution');
    });
    el.editModal.addEventListener('hidden.bs.modal', () => {
      // 未保存就关闭:清理本次会话新上传但未落库的临时文件,避免遗留孤儿文件
      if (!state.editSaved) {
        state.tempUploads.forEach((name) => {
          apiFetch('/api/delete_question_image', { method: 'POST', body: { filename: name } })
            .catch(() => {});
        });
      }
      state.tempUploads.clear();
      state.editSaved = false;
    });

    // ---- 右键菜单
    el.contextMenu.addEventListener('click', onContextMenuClick);
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#contextMenu')) hideContextMenu();
    });
    document.addEventListener('scroll', hideContextMenu, true);
    window.addEventListener('resize', hideContextMenu);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') hideContextMenu();
    });
  }

  /* ============================================================ 4. 视图切换 */

  /** 切换表格/卡片视图并记忆到 localStorage */
  function setViewMode(mode, persist = true) {
    state.viewMode = mode === 'card' ? 'card' : 'table';
    el.btnViewTable.classList.toggle('active', state.viewMode === 'table');
    el.btnViewCard.classList.toggle('active', state.viewMode === 'card');
    el.tableView.classList.toggle('d-none', state.viewMode !== 'table');
    el.cardView.classList.toggle('d-none', state.viewMode !== 'card');
    if (persist) lsSet(LS_KEYS.viewMode, state.viewMode);
    renderQuestions();
  }

  /** 从 localStorage 恢复视图模式 */
  function restoreViewMode() {
    const saved = lsGet(LS_KEYS.viewMode);
    setViewMode(saved === 'card' ? 'card' : 'table', false);
  }

  /* ============================================================ 5. 筛选与高级搜索 */

  /** 收集当前全部筛选条件(基础 + 高级) */
  function collectFilters() {
    return {
      school: el.filterSchool.value,
      major: el.filterMajor.value,
      year: el.filterYear.value,
      subjectGroup: el.filterSubjectGroup.value,
      subject: el.filterSubject.value,
      chapter: el.filterChapter.value,
      difficulty: el.filterDifficulty.value,
      masteryStatus: el.filterMastery.value,
      source: el.filterSource.value.trim(),
      search: el.filterSearch.value.trim(),
      questionId: el.advQuestionId.value.trim(),
      tagFilter: el.advTags.value.trim(),
      dateFrom: el.advDateFrom.value,
      dateTo: el.advDateTo.value,
    };
  }

  /** 把一组筛选条件写回表单控件(章节选项需先按课程联动加载) */
  async function applyFilterState(filters) {
    const f = filters || {};
    // 院試定位:先写院校再重建専攻级联,才能正确选中専攻
    el.filterSchool.value = f.school || '';
    populateMajors(f.school || '');
    el.filterMajor.value = f.major || '';
    el.filterYear.value = f.year || '';
    el.filterSubjectGroup.value = f.subjectGroup || '';
    markLocatorActive();
    el.filterSubject.value = f.subject || '';
    await loadChapterOptions(f.chapter || '');
    el.filterDifficulty.value = f.difficulty || '';
    el.filterMastery.value = f.masteryStatus || '';
    el.filterSource.value = f.source || '';
    el.filterSearch.value = f.search || '';
    el.advQuestionId.value = f.questionId || '';
    el.advTags.value = f.tagFilter || '';
    el.advDateFrom.value = f.dateFrom || '';
    el.advDateTo.value = f.dateTo || '';
    state.page = 1;
  }

  /**
   * 按当前课程加载章节下拉选项(联动),并顺带刷新来源 datalist。
   * @param {string} selected 加载后要选中的章节(不在字典中也会补一项)
   */
  async function loadChapterOptions(selected) {
    const subject = el.filterSubject.value;
    let chapters = [];
    try {
      const resp = await apiFetch('/api/questions/filters' + buildQuery({ subject }));
      chapters = (resp.data && resp.data.chapters) || [];
      fillDatalist(el.sourceOptions, (resp.data && resp.data.sources) || []);
    } catch (e) {
      console.warn('加载筛选字典失败:', e.message);
    }
    const current = selected !== undefined ? selected : el.filterChapter.value;
    const opts = ['<option value="">全部章节</option>']
      .concat(chapters.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`));
    if (current && chapters.indexOf(current) === -1) {
      opts.push(`<option value="${escapeHtml(current)}">${escapeHtml(current)}</option>`);
    }
    el.filterChapter.innerHTML = opts.join('');
    el.filterChapter.value = current || '';
  }

  // ---- 院試定位筛选:院校→専攻级联 + 年份 + 学科范围(数据来自 /api/questions/facets) ----
  let facets = { schools: [], years: [], subjectGroups: [] };

  async function loadFacets() {
    try {
      const resp = await apiFetch('/api/questions/facets');
      facets = (resp && resp.data) || facets;
    } catch (e) {
      console.warn('加载定位筛选字典失败:', e.message);
      return;
    }
    const opt = (v, label) => `<option value="${escapeHtml(v)}">${escapeHtml(label)}</option>`;
    el.filterSchool.innerHTML = ['<option value="">全部院校</option>']
      .concat((facets.schools || []).map((s) => opt(s.name, `${s.name}(${s.count})`))).join('');
    el.filterYear.innerHTML = ['<option value="">全部年份</option>']
      .concat((facets.years || []).map((y) => opt(y, y))).join('');
    el.filterSubjectGroup.innerHTML = ['<option value="">全部学科</option>']
      .concat((facets.subjectGroups || []).map((g) => opt(g.name, `${g.name}(${g.count})`))).join('');
    populateMajors('');
  }

  function populateMajors(school) {
    const entry = (facets.schools || []).find((s) => s.name === school);
    const majors = entry ? entry.majors : [];
    el.filterMajor.innerHTML = ['<option value="">全部専攻</option>']
      .concat(majors.map((m) => `<option value="${escapeHtml(m.name)}">${escapeHtml(m.name)}(${m.count})</option>`))
      .join('');
    el.filterMajor.value = '';
    el.filterMajor.disabled = !majors.length;   // 未选院校或该校单一専攻时禁用
  }

  function markLocatorActive() {
    [['filterSchool'], ['filterMajor'], ['filterYear'], ['filterSubjectGroup']].forEach(([id]) => {
      el[id].classList.toggle('filter-active', !!el[id].value);
    });
  }

  /** 重置到第一页并加载(筛选变更/执行搜索的统一入口) */
  function resetAndLoad(opts) {
    state.page = 1;
    loadQuestions(opts);
  }

  /* ============================================================ 6. 搜索历史与筛选预设 */

  /** 有值的筛选条件才会进入历史;去重后置顶,最多保留 HISTORY_LIMIT 条 */
  function recordHistory(filters) {
    const hasValue = Object.keys(filters).some((k) => filters[k]);
    if (!hasValue) return;
    const list = lsGetJson(LS_KEYS.history, []);
    const key = JSON.stringify(filters);
    const deduped = list.filter((h) => JSON.stringify(h.filters) !== key);
    deduped.unshift({ filters, time: Date.now() });
    lsSetJson(LS_KEYS.history, deduped.slice(0, HISTORY_LIMIT));
    renderHistoryMenu();
  }

  /** 用中文标签概括一组筛选条件 */
  function summarizeFilters(filters) {
    const parts = [];
    Object.keys(FILTER_LABELS).forEach((k) => {
      if (filters && filters[k]) parts.push(`${FILTER_LABELS[k]}:${filters[k]}`);
    });
    return parts.join(' | ') || '(全部题目)';
  }

  /** 渲染搜索历史下拉 */
  function renderHistoryMenu() {
    const list = lsGetJson(LS_KEYS.history, []);
    if (!list.length) {
      el.historyMenu.innerHTML = '<li><span class="dropdown-item-text text-muted">暂无搜索历史</span></li>';
      return;
    }
    const items = list.map((h, i) => (
      `<li><a class="dropdown-item history-item" href="#" data-index="${i}">
        ${escapeHtml(summarizeFilters(h.filters))}<br><small>${escapeHtml(formatTimestamp(h.time))}</small>
      </a></li>`
    ));
    items.push('<li><hr class="dropdown-divider"></li>');
    items.push('<li><a class="dropdown-item text-danger history-clear" href="#"><i class="fa-solid fa-trash me-1"></i>清空历史</a></li>');
    el.historyMenu.innerHTML = items.join('');
  }

  /** 历史下拉点击:回放或清空 */
  async function onHistoryMenuClick(e) {
    const clear = e.target.closest('.history-clear');
    if (clear) {
      e.preventDefault();
      lsSetJson(LS_KEYS.history, []);
      renderHistoryMenu();
      showToast('搜索历史已清空', 'info');
      return;
    }
    const item = e.target.closest('.history-item');
    if (!item) return;
    e.preventDefault();
    const list = lsGetJson(LS_KEYS.history, []);
    const entry = list[parseInt(item.dataset.index, 10)];
    if (!entry) return;
    await applyFilterState(entry.filters);
    loadQuestions({ record: false });
  }

  /** 保存当前筛选条件为命名预设(同名覆盖) */
  function saveCurrentPreset() {
    const name = el.presetNameInput.value.trim();
    if (!name) {
      showToast('请输入预设名称', 'warning');
      el.presetNameInput.focus();
      return;
    }
    const filters = collectFilters();
    const presets = lsGetJson(LS_KEYS.presets, []).filter((p) => p.name !== name);
    presets.unshift({ name, filters });
    lsSetJson(LS_KEYS.presets, presets);
    el.presetNameInput.value = '';
    renderPresetList();
    showToast(`预设「${name}」已保存`, 'success');
  }

  /** 渲染预设列表 */
  function renderPresetList() {
    const presets = lsGetJson(LS_KEYS.presets, []);
    if (!presets.length) {
      el.presetList.innerHTML = '<div class="text-muted small px-2 py-1">暂无预设,输入名称保存当前筛选条件</div>';
      return;
    }
    el.presetList.innerHTML = presets.map((p, i) => (
      `<div class="preset-row" data-index="${i}">
        <span class="preset-load" title="${escapeHtml(summarizeFilters(p.filters))}">
          <i class="fa-solid fa-filter me-1 text-primary"></i>${escapeHtml(p.name)}
        </span>
        <i class="fa-solid fa-trash text-danger preset-delete" role="button" title="删除预设"></i>
      </div>`
    )).join('');
  }

  /** 预设列表点击:加载或删除 */
  async function onPresetListClick(e) {
    const row = e.target.closest('.preset-row');
    if (!row) return;
    const presets = lsGetJson(LS_KEYS.presets, []);
    const index = parseInt(row.dataset.index, 10);
    const preset = presets[index];
    if (!preset) return;

    if (e.target.closest('.preset-delete')) {
      presets.splice(index, 1);
      lsSetJson(LS_KEYS.presets, presets);
      renderPresetList();
      showToast(`预设「${preset.name}」已删除`, 'info');
      return;
    }
    if (e.target.closest('.preset-load')) {
      await applyFilterState(preset.filters);
      loadQuestions({ record: false });
      const dropdown = bootstrap.Dropdown.getInstance(el.btnPresetDropdown);
      if (dropdown) dropdown.hide();
      showToast(`已应用预设「${preset.name}」`, 'info');
    }
  }

  /* ============================================================ 7. 数据加载与渲染 */

  /**
   * 加载题目列表。
   * @param {{record?: boolean}} opts record=false 时不写入搜索历史(分页/回放等场景)
   */
  async function loadQuestions(opts) {
    const options = opts || {};
    const filters = collectFilters();
    const seq = ++loadSeq;
    showLoading();
    try {
      const params = Object.assign({}, filters, { page: state.page, per_page: state.perPage });
      const resp = await apiFetch('/api/questions' + buildQuery(params));
      if (seq !== loadSeq) return;   // 已有更新的请求发出,丢弃这次过期响应
      const d = resp.data || {};
      state.questions = d.questions || [];
      state.total = d.total || 0;
      state.page = d.page || 1;
      state.pages = d.pages || 0;
      renderQuestions();
      renderPagination();
      refreshBookmarks();
      refreshProgress();
      if (options.record !== false) recordHistory(filters);
    } catch (e) {
      if (seq !== loadSeq) return;
      showToast(e.message, 'danger');
      renderLoadError();
    }
  }

  /** 在当前激活视图内显示加载状态 */
  function showLoading() {
    const spinner = '<div class="empty-hint"><div class="spinner-border text-primary" role="status"></div><div class="mt-2">加载中...</div></div>';
    if (state.viewMode === 'table') {
      el.questionTbody.innerHTML = `<tr><td colspan="9">${spinner}</td></tr>`;
    } else {
      el.cardView.innerHTML = spinner;
    }
  }

  /** 加载失败提示 */
  function renderLoadError() {
    const hint = '<div class="empty-hint"><i class="fa-solid fa-triangle-exclamation me-1"></i>加载失败,请稍后重试</div>';
    if (state.viewMode === 'table') {
      el.questionTbody.innerHTML = `<tr><td colspan="9">${hint}</td></tr>`;
    } else {
      el.cardView.innerHTML = hint;
    }
  }

  /** 表格行 HTML */
  function questionRowHtml(q) {
    const selected = state.selected.has(q.id);
    const marked = state.bookmarked.has(q.id);
    return `
      <tr data-id="${q.id}" class="${selected ? 'selected' : ''}">
        <td><input type="checkbox" class="form-check-input row-check" data-id="${q.id}" ${selected ? 'checked' : ''}></td>
        <td class="text-nowrap"><span class="mastery-dot" data-id="${q.id}" title="做题状态"></span>#${q.id}</td>
        <td class="text-nowrap">${escapeHtml(q.subject)}</td>
        <td>${escapeHtml(q.chapter || '-')}</td>
        <td>${difficultyBadge(q.difficulty)}</td>
        <td>${escapeHtml(q.source || '-')}</td>
        <td>${tagBadges(q.tags) || '<span class="text-muted">-</span>'}</td>
        <td style="min-width:260px">
          <div class="latex-content js-open-detail" data-id="${q.id}" title="点击查看详情">${escapeHtml(q.question_latex || '(无内容)')}</div>
        </td>
        <td class="text-nowrap">
          <i class="fa-solid fa-bookmark bookmark-btn${marked ? ' bookmarked' : ''} me-2" data-id="${q.id}" title="加入/移出错题本"></i>
          <a class="btn btn-sm btn-outline-secondary me-1" href="/questions/${q.id}" title="打开双语题解详情页"><i class="fa-solid fa-up-right-from-square"></i></a>
          <button type="button" class="btn btn-sm btn-outline-primary js-edit" data-id="${q.id}" title="编辑"><i class="fa-solid fa-pen"></i></button>
          <button type="button" class="btn btn-sm btn-outline-danger js-delete" data-id="${q.id}" title="删除"><i class="fa-solid fa-trash"></i></button>
        </td>
      </tr>`;
  }

  /** 卡片 HTML */
  function questionCardHtml(q) {
    const selected = state.selected.has(q.id);
    const marked = state.bookmarked.has(q.id);
    return `
      <div class="question-card-item${selected ? ' selected' : ''}" data-id="${q.id}">
        <div class="d-flex align-items-center gap-2 mb-2">
          <input type="checkbox" class="form-check-input row-check m-0" data-id="${q.id}" ${selected ? 'checked' : ''}>
          <span class="fw-semibold"><span class="mastery-dot" data-id="${q.id}" title="做题状态"></span>#${q.id}</span>
          <span class="badge bg-light text-dark border">${escapeHtml(q.subject)}</span>
          ${difficultyBadge(q.difficulty)}
          <i class="fa-solid fa-bookmark bookmark-btn${marked ? ' bookmarked' : ''} ms-auto" data-id="${q.id}" title="加入/移出错题本"></i>
        </div>
        <div class="latex-content card-latex-clip js-open-detail" data-id="${q.id}" title="点击查看详情">${escapeHtml(q.question_latex || '(无内容)')}</div>
        <div class="mt-2">${tagBadges(q.tags)}</div>
        <div class="text-muted small mt-1">
          ${escapeHtml(q.chapter || '-')} · ${escapeHtml(q.source || '-')} · ${escapeHtml(formatDate(q.created_at))}
        </div>
        <div class="d-flex gap-2 mt-2 pt-2 border-top">
          <button type="button" class="btn btn-sm btn-outline-secondary js-open-detail" data-id="${q.id}"><i class="fa-solid fa-eye me-1"></i>详情</button>
          <a class="btn btn-sm btn-outline-secondary" href="/questions/${q.id}" title="打开双语题解详情页"><i class="fa-solid fa-up-right-from-square me-1"></i>详情页 ↗</a>
          <button type="button" class="btn btn-sm btn-outline-primary js-edit" data-id="${q.id}"><i class="fa-solid fa-pen me-1"></i>编辑</button>
          <button type="button" class="btn btn-sm btn-outline-danger js-delete" data-id="${q.id}"><i class="fa-solid fa-trash me-1"></i>删除</button>
        </div>
      </div>`;
  }

  /** 渲染当前激活视图并重排公式 */
  function renderQuestions() {
    const empty = '<div class="empty-hint"><i class="fa-regular fa-folder-open me-1"></i>暂无符合条件的题目</div>';
    if (state.viewMode === 'table') {
      el.questionTbody.innerHTML = state.questions.length
        ? state.questions.map(questionRowHtml).join('')
        : `<tr><td colspan="9">${empty}</td></tr>`;
      typesetMath(el.questionTbody);
    } else {
      el.cardView.innerHTML = state.questions.length
        ? state.questions.map(questionCardHtml).join('')
        : empty;
      typesetMath(el.cardView);
    }
    syncCheckAll();
    updateBatchToolbar();
  }

  /** 计算分页页码序列(含省略号) */
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

  /** 渲染分页组件与结果统计 */
  function renderPagination() {
    const totalPages = Math.max(state.pages, 1);
    const page = state.page;
    const item = (p, label, disabled, active) => (
      `<li class="page-item${disabled ? ' disabled' : ''}${active ? ' active' : ''}">
        <a class="page-link" href="#" data-page="${p}">${label}</a>
      </li>`
    );
    const parts = [item(page - 1, '&laquo;', page <= 1, false)];
    pageNumbers(page, totalPages).forEach((n) => {
      if (n === '...') {
        parts.push('<li class="page-item disabled"><span class="page-link">…</span></li>');
      } else {
        parts.push(item(n, String(n), false, n === page));
      }
    });
    parts.push(item(page + 1, '&raquo;', page >= totalPages, false));
    el.paginationList.innerHTML = parts.join('');
    el.resultSummary.textContent = `共 ${state.total} 条记录,第 ${page} / ${totalPages} 页`;
  }

  /** 分页点击 */
  function onPaginationClick(e) {
    e.preventDefault();
    const link = e.target.closest('a.page-link');
    if (!link || link.closest('.disabled') || link.closest('.active')) return;
    const p = parseInt(link.dataset.page, 10);
    if (!p || p < 1 || p > Math.max(state.pages, 1) || p === state.page) return;
    state.page = p;
    loadQuestions({ record: false });
  }

  /** 列表点击(事件委托,表格/卡片共用) */
  function onListClick(e) {
    const dot = e.target.closest('.mastery-dot');
    if (dot) { cycleMastery(Number(dot.dataset.id)); return; }

    const bookmark = e.target.closest('.bookmark-btn');
    if (bookmark) { toggleBookmark(Number(bookmark.dataset.id)); return; }

    const check = e.target.closest('.row-check');
    if (check) { toggleSelect(Number(check.dataset.id), check.checked); return; }

    const editBtn = e.target.closest('.js-edit');
    if (editBtn) { startEdit(Number(editBtn.dataset.id)); return; }

    const delBtn = e.target.closest('.js-delete');
    if (delBtn) { deleteQuestion(Number(delBtn.dataset.id)); return; }

    const openBtn = e.target.closest('.js-open-detail');
    if (openBtn) openDetail(Number(openBtn.dataset.id));
  }

  /* ============================================================ 8. 选择与批量操作 */

  /** 切换单题选中态(选中项跨页保留) */
  function toggleSelect(id, on) {
    const next = on === undefined ? !state.selected.has(id) : !!on;
    if (next) state.selected.add(id); else state.selected.delete(id);
    updateSelectionDom(id, next);
    syncCheckAll();
    updateBatchToolbar();
  }

  /** 同步某题的行/卡片选中样式与复选框 */
  function updateSelectionDom(id, on) {
    document
      .querySelectorAll(`#tableView tr[data-id="${id}"], #cardView .question-card-item[data-id="${id}"]`)
      .forEach((node) => {
        node.classList.toggle('selected', on);
        const cb = node.querySelector('.row-check');
        if (cb) cb.checked = on;
      });
  }

  /** 全选/取消全选当前页 */
  function selectAllCurrentPage(on) {
    state.questions.forEach((q) => {
      if (on) state.selected.add(q.id); else state.selected.delete(q.id);
      updateSelectionDom(q.id, on);
    });
    syncCheckAll();
    updateBatchToolbar();
  }

  /** 同步两个"全选"复选框的勾选/半选状态 */
  function syncCheckAll() {
    const ids = state.questions.map((q) => q.id);
    const selectedCount = ids.filter((id) => state.selected.has(id)).length;
    [el.checkAll, el.checkAllPage].forEach((cb) => {
      if (!cb) return;
      cb.checked = ids.length > 0 && selectedCount === ids.length;
      cb.indeterminate = selectedCount > 0 && selectedCount < ids.length;
    });
  }

  /** 根据选中数量显示/隐藏批量工具栏 */
  function updateBatchToolbar() {
    const n = state.selected.size;
    el.batchToolbar.classList.toggle('d-none', n === 0);
    el.batchCount.textContent = `已选中 ${n} 项`;
  }

  /** 取消全部选择 */
  function clearSelection() {
    Array.from(state.selected).forEach((id) => updateSelectionDom(id, false));
    state.selected.clear();
    syncCheckAll();
    updateBatchToolbar();
  }

  /** 有选中项才继续,否则提示 */
  function ensureSelection() {
    if (state.selected.size === 0) {
      showToast('请先选择题目', 'warning');
      return false;
    }
    return true;
  }

  /** 批量删除 */
  async function batchDelete() {
    if (!ensureSelection()) return;
    const ids = Array.from(state.selected);
    if (!window.confirm(`确定删除选中的 ${ids.length} 道题目吗?删除后不可恢复。`)) return;
    try {
      const resp = await apiFetch('/api/questions/batch_delete', { method: 'POST', body: { ids } });
      showToast(resp.message || `已删除 ${(resp.data && resp.data.deleted) || 0} 道题目`, 'success');
      clearSelection();
      state.page = 1;
      loadQuestions({ record: false });
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  /** 打开批量编辑标签弹窗 */
  function openBatchTagsModal() {
    if (!ensureSelection()) return;
    el.batchTagsCount.textContent = String(state.selected.size);
    el.batchTagsInput.value = '';
    document.getElementById('modeReplace').checked = true;
    modals.batchTags.show();
  }

  /** 确认批量编辑标签 */
  async function confirmBatchTags() {
    const ids = Array.from(state.selected);
    if (!ids.length) { modals.batchTags.hide(); return; }
    const modeInput = document.querySelector('input[name="batchTagsMode"]:checked');
    const mode = modeInput ? modeInput.value : 'replace';
    const tags = parseTagsInput(el.batchTagsInput.value);
    if (mode === 'add' && !tags.length) {
      showToast('追加模式下请至少输入一个标签', 'warning');
      return;
    }
    if (mode === 'replace' && !tags.length
        && !window.confirm('标签为空,将清空所选题目的全部标签,确定继续吗?')) return;
    try {
      const resp = await apiFetch('/api/questions/batch_update_tags', {
        method: 'POST', body: { ids, tags, mode },
      });
      showToast(resp.message || `已更新 ${(resp.data && resp.data.updated) || 0} 道题目的标签`, 'success');
      modals.batchTags.hide();
      loadQuestions({ record: false });
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  /** 打开批量修改来源弹窗 */
  function openBatchSourceModal() {
    if (!ensureSelection()) return;
    el.batchSourceCount.textContent = String(state.selected.size);
    el.batchSourceInput.value = '';
    modals.batchSource.show();
  }

  /** 确认批量修改来源 */
  async function confirmBatchSource() {
    const ids = Array.from(state.selected);
    if (!ids.length) { modals.batchSource.hide(); return; }
    const source = el.batchSourceInput.value.trim();
    if (!source) {
      showToast('请输入新来源', 'warning');
      el.batchSourceInput.focus();
      return;
    }
    try {
      const resp = await apiFetch('/api/questions/batch_update_source', {
        method: 'POST', body: { ids, source },
      });
      showToast(resp.message || `已更新 ${(resp.data && resp.data.updated) || 0} 道题目的来源`, 'success');
      modals.batchSource.hide();
      loadQuestions({ record: false });
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  /** 批量加入错题本 */
  async function batchAddErrorBook() {
    if (!ensureSelection()) return;
    const ids = Array.from(state.selected);
    try {
      const resp = await apiFetch('/api/error_book/add_batch', {
        method: 'POST', body: { question_ids: ids },
      });
      const d = resp.data || {};
      const added = d.added != null ? d.added : 0;
      let msg = `已加入错题本 ${added} 题`;
      if (d.skipped) msg += `,跳过 ${d.skipped} 题(已在错题本中)`;
      showToast(msg, 'success');
      refreshBookmarks();
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  /* ============================================================ 9. 书签(错题本) */

  /** 渲染列表后批量回填书签状态(错题本模块不可用时静默降级) */
  async function refreshBookmarks() {
    const ids = state.questions.map((q) => q.id);
    if (!ids.length) return;
    try {
      const resp = await apiFetch('/api/error_book/check_batch', {
        method: 'POST', body: { question_ids: ids },
      });
      const marked = new Set((resp.data && resp.data.in_error_book) || []);
      ids.forEach((id) => {
        if (marked.has(id)) state.bookmarked.add(id); else state.bookmarked.delete(id);
        updateBookmarkDom(id);
      });
    } catch (e) {
      console.warn('错题本状态查询失败:', e.message);
    }
  }

  /** 切换某题的错题本收藏状态 */
  async function toggleBookmark(id) {
    const marked = state.bookmarked.has(id);
    try {
      if (marked) {
        await apiFetch('/api/error_book/remove', { method: 'POST', body: { question_id: id } });
        state.bookmarked.delete(id);
        showToast('已移出错题本', 'info');
      } else {
        const resp = await apiFetch('/api/error_book/add', { method: 'POST', body: { question_id: id } });
        state.bookmarked.add(id);
        showToast(resp.message || '已加入错题本', 'success');
      }
      updateBookmarkDom(id);
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  /** 同步某题在列表与详情弹窗中的书签外观 */
  function updateBookmarkDom(id) {
    const marked = state.bookmarked.has(id);
    document
      .querySelectorAll(`#tableView .bookmark-btn[data-id="${id}"], #cardView .bookmark-btn[data-id="${id}"]`)
      .forEach((btn) => btn.classList.toggle('bookmarked', marked));
    if (state.detailId === id) updateDetailBookmarkBtn();
  }

  /* ==================================================== 9b. 掌握状态(做题进度) */

  /** 渲染列表后批量回填做题状态色块(进度模块不可用时静默降级) */
  async function refreshProgress() {
    const ids = state.questions.map((q) => q.id);
    if (!ids.length) return;
    try {
      const resp = await apiFetch('/api/progress/check_batch', {
        method: 'POST', body: { question_ids: ids },
      });
      const statuses = (resp.data && resp.data.statuses) || {};
      ids.forEach((id) => {
        const st = statuses[String(id)];
        if (st) state.mastery.set(id, st); else state.mastery.delete(id);
        updateMasteryDom(id);
      });
    } catch (e) {
      console.warn('做题状态查询失败:', e.message);
    }
  }

  /** 同步某题在列表/卡片中的状态色块外观 */
  function updateMasteryDom(id) {
    const status = state.mastery.get(id);   // 'done' | 'mastered' | undefined(未做)
    document
      .querySelectorAll(`#tableView .mastery-dot[data-id="${id}"], #cardView .mastery-dot[data-id="${id}"]`)
      .forEach((dot) => {
        dot.classList.toggle('is-done', status === 'done');
        dot.classList.toggle('is-mastered', status === 'mastered');
        dot.classList.toggle('is-new', !status);
      });
  }

  /** 点击色块循环切换 未做→做过→已掌握→未做,并写回后端 */
  async function cycleMastery(id) {
    const current = state.mastery.get(id);            // undefined | 'done' | 'mastered'
    const next = current === 'done' ? 'mastered' : current === 'mastered' ? 'none' : 'done';
    try {
      await apiFetch('/api/progress/set', { method: 'POST', body: { question_id: id, status: next } });
      if (next === 'none') state.mastery.delete(id); else state.mastery.set(id, next);
      updateMasteryDom(id);
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  /* ============================================================ 10. 题目详情 Modal */

  /** 打开题目详情弹窗(五区块;打开时记录查看日志) */
  async function openDetail(id) {
    let question;
    try {
      const resp = await apiFetch(`/api/questions/${id}`);
      question = resp.data.question;
    } catch (e) {
      showToast(e.message, 'danger');
      return;
    }
    state.detailId = id;

    // 区块一:题目信息
    el.detailQid.textContent = `#${question.id}`;
    const openPageLink = document.getElementById('btnDetailOpenPage');
    if (openPageLink) openPageLink.href = `/questions/${question.id}`;
    el.detailInfo.innerHTML = `
      <div class="col-md-4 detail-info-item"><span class="text-muted">编号:</span>#${question.id}</div>
      <div class="col-md-4 detail-info-item"><span class="text-muted">科目:</span>${escapeHtml(question.subject)}</div>
      <div class="col-md-4 detail-info-item"><span class="text-muted">难度:</span>${difficultyBadge(question.difficulty)}</div>
      <div class="col-md-4 detail-info-item"><span class="text-muted">年份/章节:</span>${escapeHtml(question.chapter || '-')}</div>
      <div class="col-md-4 detail-info-item"><span class="text-muted">出处:</span>${escapeHtml(question.source || '-')}</div>
      <div class="col-md-4 detail-info-item"><span class="text-muted">创建时间:</span>${escapeHtml(question.created_at || '-')}</div>
      <div class="col-12 detail-info-item"><span class="text-muted">标签:</span>${tagBadges(question.tags) || '<span class="text-muted">无</span>'}</div>`;

    // 区块二/三:题目内容与图片
    el.detailQuestionLatex.innerHTML = question.question_latex
      ? escapeHtml(question.question_latex)
      : '<span class="text-muted">(无题目内容)</span>';
    el.detailQuestionImage.innerHTML = imageBlockHtml(question.question_image_url, question.question_image);

    // 区块四/五:解答内容与图片(默认折叠)
    el.detailSolutionLatex.innerHTML = question.solution_latex
      ? escapeHtml(question.solution_latex)
      : '<span class="text-muted">(无解答内容)</span>';
    el.detailSolutionImage.innerHTML = imageBlockHtml(question.solution_image_url, question.solution_image);
    el.detailSolutionWrap.classList.add('d-none');
    el.btnToggleSolution.innerHTML = '<i class="fa-solid fa-eye me-1"></i>查看答案';

    updateDetailBookmarkBtn();
    modals.detail.show();
    typesetMath(el.detailModal);

    // 记录查看日志(静默,不打断浏览)
    apiFetch('/api/log_view_question', { method: 'POST', body: { question_id: id } })
      .catch((e) => console.warn('记录查看日志失败:', e.message));
  }

  /** 附件展示块:图片直接内嵌,PDF 给链接,空则占位 */
  function imageBlockHtml(url, filename) {
    if (!url) return '<span class="text-muted">(无)</span>';
    if (/\.pdf$/i.test(filename || url)) {
      return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-secondary">
        <i class="fa-regular fa-file-pdf me-1"></i>查看 PDF 附件</a>`;
    }
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">
      <img src="${escapeHtml(url)}" class="question-detail-image" alt="附件图片"></a>`;
  }

  /** 展开/收起解答区块 */
  function toggleDetailSolution() {
    const hidden = el.detailSolutionWrap.classList.toggle('d-none');
    el.btnToggleSolution.innerHTML = hidden
      ? '<i class="fa-solid fa-eye me-1"></i>查看答案'
      : '<i class="fa-solid fa-eye-slash me-1"></i>收起答案';
    if (!hidden) typesetMath(el.detailSolutionWrap);
  }

  /** 详情弹窗内的书签按钮外观 */
  function updateDetailBookmarkBtn() {
    if (state.detailId == null) return;
    const marked = state.bookmarked.has(state.detailId);
    el.btnDetailBookmark.innerHTML = marked
      ? '<i class="fa-solid fa-bookmark me-1"></i>移出错题本'
      : '<i class="fa-regular fa-bookmark me-1"></i>加入错题本';
    el.btnDetailBookmark.classList.toggle('btn-warning', marked);
    el.btnDetailBookmark.classList.toggle('btn-outline-warning', !marked);
  }

  /* ============================================================ 11. 右键上下文菜单 */

  /** 表格行/卡片上的 contextmenu */
  function onListContextMenu(e) {
    const host = e.target.closest('tr[data-id], .question-card-item[data-id]');
    if (!host) return;
    e.preventDefault();
    state.contextTargetId = Number(host.dataset.id);
    el.ctxBookmarkText.textContent = state.bookmarked.has(state.contextTargetId) ? '移出错题本' : '加入错题本';

    const menu = el.contextMenu;
    menu.style.display = 'block';
    const rect = menu.getBoundingClientRect();
    let x = e.clientX;
    let y = e.clientY;
    if (x + rect.width > window.innerWidth) x = Math.max(window.innerWidth - rect.width - 8, 0);
    if (y + rect.height > window.innerHeight) y = Math.max(window.innerHeight - rect.height - 8, 0);
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
  }

  function hideContextMenu() {
    el.contextMenu.style.display = 'none';
  }

  /** 菜单项分发 */
  function onContextMenuClick(e) {
    const item = e.target.closest('.context-menu-item');
    if (!item) return;
    const id = state.contextTargetId;
    hideContextMenu();
    if (id == null) return;
    switch (item.dataset.action) {
      case 'detail': openDetail(id); break;
      case 'edit': startEdit(id); break;
      case 'bookmark': toggleBookmark(id); break;
      case 'copy': copyQuestionLatex(id); break;
      case 'delete': deleteQuestion(id); break;
      default: break;
    }
  }

  /** 复制题目 LaTeX 到剪贴板 */
  async function copyQuestionLatex(id) {
    let question = state.questions.find((q) => q.id === id);
    if (!question) {
      try {
        question = (await apiFetch(`/api/questions/${id}`)).data.question;
      } catch (e) {
        showToast(e.message, 'danger');
        return;
      }
    }
    const text = question.question_latex || '';
    if (!text) {
      showToast('该题目暂无 LaTeX 内容', 'warning');
      return;
    }
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
      }
      showToast('题目 LaTeX 已复制到剪贴板', 'success');
    } catch (e) {
      showToast('复制失败,请手动复制', 'danger');
    }
  }

  /** 删除单题 */
  async function deleteQuestion(id) {
    if (!window.confirm(`确定删除题目 #${id} 吗?删除后不可恢复。`)) return;
    try {
      const resp = await apiFetch(`/api/questions/${id}`, { method: 'DELETE' });
      showToast(resp.message || '删除成功', 'success');
      state.selected.delete(id);
      state.bookmarked.delete(id);
      if (state.questions.length === 1 && state.page > 1) state.page -= 1;
      loadQuestions({ record: false });
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  /* ============================================================ 12. 新建/编辑 Modal */

  /** 懒初始化 CodeMirror(CDN 失败时降级为原生 textarea) */
  function ensureEditors() {
    if (editorsInitialized) return;
    editorsInitialized = true;
    if (typeof CodeMirror !== 'undefined') {
      const options = { mode: 'stex', lineNumbers: true, lineWrapping: true, viewportMargin: Infinity };
      editors.question = CodeMirror.fromTextArea(el.editQuestionLatex, options);
      editors.solution = CodeMirror.fromTextArea(el.editSolutionLatex, options);
      editors.question.on('change', debounce(() => updatePreview('question'), 500));
      editors.solution.on('change', debounce(() => updatePreview('solution'), 500));
    } else {
      showToast('LaTeX 编辑器组件加载失败,已降级为纯文本输入', 'warning');
      el.editQuestionLatex.addEventListener('input', debounce(() => updatePreview('question'), 500));
      el.editSolutionLatex.addEventListener('input', debounce(() => updatePreview('solution'), 500));
    }
  }

  /** 读取 LaTeX 编辑器内容(兼容降级) */
  function getLatexValue(which) {
    if (editors[which]) return editors[which].getValue();
    return which === 'question' ? el.editQuestionLatex.value : el.editSolutionLatex.value;
  }

  /** 写入 LaTeX 编辑器内容(兼容降级) */
  function setLatexValue(which, value) {
    if (editors[which]) {
      editors[which].setValue(value || '');
    } else if (which === 'question') {
      el.editQuestionLatex.value = value || '';
    } else {
      el.editSolutionLatex.value = value || '';
    }
  }

  /** 刷新实时预览(escapeHtml 后交给 MathJax 处理文本层) */
  function updatePreview(which) {
    const target = which === 'question' ? el.previewQuestion : el.previewSolution;
    const value = getLatexValue(which);
    target.innerHTML = value.trim()
      ? escapeHtml(value)
      : '<span class="text-muted">(实时预览)</span>';
    typesetMath(target);
  }

  /** 拉取最新数据后进入编辑 */
  async function startEdit(id) {
    try {
      const resp = await apiFetch(`/api/questions/${id}`);
      openEditModal(resp.data.question);
    } catch (e) {
      showToast(e.message, 'danger');
    }
  }

  /**
   * 打开新建/编辑弹窗。
   * @param {object|null} question null 表示新建
   */
  function openEditModal(question) {
    ensureEditors();
    state.editingId = question ? question.id : null;
    el.editModalTitle.textContent = question ? `编辑题目 #${question.id}` : '新建题目';
    el.editSubject.value = question ? question.subject : '';
    el.editChapter.value = question ? (question.chapter || '') : '';
    el.editDifficulty.value = question ? question.difficulty : '中等';
    el.editSource.value = question ? (question.source || '') : '';
    el.editTags.value = question ? (question.tags || []).join(', ') : '';
    setLatexValue('question', question ? question.question_latex : '');
    setLatexValue('solution', question ? question.solution_latex : '');
    state.editImages.question_image = question ? (question.question_image || null) : null;
    state.editImages.solution_image = question ? (question.solution_image || null) : null;
    state.tempUploads.clear();   // 本次编辑会话尚未上传任何临时文件
    state.editSaved = false;
    renderImagePreview('question_image');
    renderImagePreview('solution_image');
    el.sourceHint.textContent = '';
    el.sourceHint.className = 'source-hint';
    el.fileQuestionImage.value = '';
    el.fileSolutionImage.value = '';
    updateEditChapterOptions();
    modals.edit.show();
  }

  /** 按弹窗中选择的课程刷新章节 datalist 建议 */
  async function updateEditChapterOptions() {
    const subject = el.editSubject.value;
    if (!subject) {
      el.editChapterOptions.innerHTML = '';
      return;
    }
    try {
      const resp = await apiFetch('/api/questions/filters' + buildQuery({ subject }));
      fillDatalist(el.editChapterOptions, (resp.data && resp.data.chapters) || []);
    } catch (e) {
      console.warn('加载章节建议失败:', e.message);
    }
  }

  /** 来源失焦判重(编辑时排除自身) */
  async function checkSourceExists() {
    const source = el.editSource.value.trim();
    el.sourceHint.textContent = '';
    el.sourceHint.className = 'source-hint';
    if (!source) return;
    try {
      const query = buildQuery({ source, exclude_id: state.editingId || '' });
      const resp = await apiFetch('/api/source_exists' + query);
      if (resp.data && resp.data.exists) {
        el.sourceHint.innerHTML = '<i class="fa-solid fa-triangle-exclamation me-1"></i>已存在相同来源的题目,请确认是否重复录入。';
        el.sourceHint.className = 'source-hint text-warning';
      } else {
        el.sourceHint.innerHTML = '<i class="fa-solid fa-circle-check me-1"></i>该来源暂无重复。';
        el.sourceHint.className = 'source-hint text-success';
      }
    } catch (e) {
      console.warn('来源判重失败:', e.message);
    }
  }

  /**
   * 上传题目/解答附件(image/* 与 PDF)。
   * @param {'question_image'|'solution_image'} kind
   * @param {HTMLInputElement} input
   */
  async function handleImageUpload(kind, input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const typeOk = file.type && (file.type.indexOf('image/') === 0 || file.type === 'application/pdf');
    if (!typeOk) {
      showToast('仅支持图片或 PDF 文件', 'warning');
      input.value = '';
      return;
    }
    const box = kind === 'question_image' ? el.questionImagePreview : el.solutionImagePreview;
    box.innerHTML = '<div class="text-muted small"><span class="spinner-border spinner-border-sm me-1"></span>上传中...</div>';
    const fd = new FormData();
    fd.append('file', file);
    try {
      const resp = await apiFetch('/api/upload_question_image', { method: 'POST', body: fd });
      const previous = state.editImages[kind];
      const uploaded = resp.data.filename;
      state.editImages[kind] = uploaded;
      state.tempUploads.add(uploaded);
      // 仅当被替换的旧附件是本次会话新上传、尚未保存的临时文件时才立即删除;
      // 题目原有的已保存附件应保留,待保存成功后由后端 _remove_image_files 清理,
      // 以免用户取消编辑后数据库仍引用一个已被物理删除的文件。
      if (previous && previous !== uploaded && state.tempUploads.has(previous)) {
        state.tempUploads.delete(previous);
        apiFetch('/api/delete_question_image', { method: 'POST', body: { filename: previous } })
          .catch(() => {});
      }
      showToast(resp.message || '上传成功', 'success');
    } catch (e) {
      showToast(e.message, 'danger');
    } finally {
      input.value = '';
      renderImagePreview(kind);
    }
  }

  /** 渲染附件缩略图 / PDF 链接与删除按钮 */
  function renderImagePreview(kind) {
    const box = kind === 'question_image' ? el.questionImagePreview : el.solutionImagePreview;
    const filename = state.editImages[kind];
    if (!filename) {
      box.innerHTML = '<span class="text-muted small">未上传附件</span>';
      return;
    }
    const url = `/uploads/${encodeURIComponent(filename)}`;
    const preview = /\.pdf$/i.test(filename)
      ? `<a href="${url}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-secondary">
          <i class="fa-regular fa-file-pdf me-1"></i>${escapeHtml(filename)}</a>`
      : `<a href="${url}" target="_blank" rel="noopener">
          <img src="${url}" class="image-preview-thumb" alt="附件预览"></a>`;
    box.innerHTML = `
      <div class="image-upload-preview">${preview}
        <button type="button" class="btn btn-sm btn-outline-danger js-remove-image" data-kind="${kind}" title="删除附件">
          <i class="fa-solid fa-trash"></i>
        </button>
      </div>`;
  }

  /**
   * 移除弹窗内的附件。
   * 临时文件(本次会话新上传、未保存)立即物理删除;题目已保存的原附件仅清空字段,
   * 待点击「保存」后由后端清理,避免取消编辑造成数据库引用悬空。
   */
  function removeEditImage(kind) {
    const filename = state.editImages[kind];
    if (!filename) return;
    if (!window.confirm('确定移除该附件吗?')) return;
    if (state.tempUploads.has(filename)) {
      state.tempUploads.delete(filename);
      apiFetch('/api/delete_question_image', { method: 'POST', body: { filename } })
        .catch(() => {});
    }
    state.editImages[kind] = null;
    renderImagePreview(kind);
    showToast('附件已移除', 'info');
  }

  /** 保存(新建 POST / 编辑 PUT) */
  async function saveQuestion() {
    const subject = el.editSubject.value;
    if (!subject) {
      showToast('请选择课程', 'warning');
      el.editSubject.focus();
      return;
    }
    const payload = {
      subject,
      chapter: el.editChapter.value.trim(),
      difficulty: el.editDifficulty.value || '中等',
      source: el.editSource.value.trim(),
      tags: parseTagsInput(el.editTags.value),
      question_latex: getLatexValue('question'),
      solution_latex: getLatexValue('solution'),
      question_image: state.editImages.question_image || '',
      solution_image: state.editImages.solution_image || '',
    };
    setBtnLoading(el.btnSaveQuestion, true, '保存中...');
    try {
      const resp = state.editingId
        ? await apiFetch(`/api/questions/${state.editingId}`, { method: 'PUT', body: payload })
        : await apiFetch('/api/questions', { method: 'POST', body: payload });
      // 保存成功:当前 editImages 已持久化,被替换的原附件由后端清理;
      // 标记已保存并清空临时文件跟踪,避免关窗时误删已保存的附件。
      state.editSaved = true;
      state.tempUploads.clear();
      showToast(resp.message || '保存成功', 'success');
      modals.edit.hide();
      loadQuestions({ record: false });
      loadChapterOptions(); // 章节/来源字典可能出现新值
    } catch (e) {
      showToast(e.message, 'danger');
    } finally {
      setBtnLoading(el.btnSaveQuestion, false);
    }
  }

  /* ============================================================ 13. 通用小工具 */

  /** 标签输入解析:中英文逗号/顿号/分号分隔,去空白去重 */
  function parseTagsInput(raw) {
    const seen = new Set();
    return String(raw || '')
      .split(/[,，、;；]/)
      .map((t) => t.trim())
      .filter((t) => {
        if (!t || seen.has(t)) return false;
        seen.add(t);
        return true;
      });
  }

  /** 填充 datalist 选项 */
  function fillDatalist(datalist, values) {
    datalist.innerHTML = (values || [])
      .map((v) => `<option value="${escapeHtml(v)}"></option>`)
      .join('');
  }

  /** 按钮 loading 态(保留原始内容以便还原) */
  function setBtnLoading(btn, loading, text) {
    if (loading) {
      btn.dataset.originalHtml = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${escapeHtml(text || '处理中...')}`;
    } else {
      btn.disabled = false;
      if (btn.dataset.originalHtml) btn.innerHTML = btn.dataset.originalHtml;
    }
  }

  /** 时间戳 → 'YYYY-MM-DD HH:MM' */
  function formatTimestamp(ts) {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  /* ---- localStorage 安全封装(隐私模式等场景下静默降级) ---- */

  function lsGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  function lsSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* 忽略 */ }
  }

  function lsGetJson(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      return Array.isArray(fallback) && !Array.isArray(parsed) ? fallback : parsed;
    } catch (e) {
      return fallback;
    }
  }

  function lsSetJson(key, value) {
    try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 忽略 */ }
  }
})();
