/**
 * 错题本页面逻辑。
 *
 * 功能:列表筛选/分页、批量移出、备注内联编辑、快速预览 Modal、
 *       顶部统计(总数 + 按科目分布)、PDF 试卷生成配置 Modal。
 * 依赖:utils.js(apiFetch/buildQuery/escapeHtml/debounce/typesetMath/
 *       difficultyBadge/tagBadges/formatDate)与 toast.js(showToast)。
 */
(function () {
  'use strict';

  /** 页面状态 */
  const state = {
    filters: { subject: '', chapter: '', difficulty: '', source: '', search: '' },
    page: 1,
    perPage: 20,
    pages: 1,
    total: 0,
    entries: [],            // 当前页错题条目(含内嵌 question)
    selected: new Set(),    // 已勾选的 question_id(跨页保留)
  };

  /** DOM 引用(init 时填充) */
  const els = {};

  /** 列表加载请求序号:仅渲染最新一次响应,防止旧响应覆盖新结果 */
  let listSeq = 0;

  document.addEventListener('DOMContentLoaded', init);

  /** 初始化:抓取 DOM、绑定事件、加载数据 */
  function init() {
    [
      'statTotal', 'statBySubject',
      'filterSubject', 'filterChapter', 'filterDifficulty', 'filterSource', 'filterSearch',
      'btnResetFilters', 'batchToolbar', 'selectedCount', 'btnBatchRemove', 'btnClearSelection',
      'checkAll', 'listSummary', 'perPageSelect', 'entryList', 'emptyState', 'pagination',
      'previewModal', 'previewInfo', 'previewQuestion', 'previewQuestionImage',
      'btnToggleSolution', 'previewSolutionWrap', 'previewSolution', 'previewSolutionImage',
      'btnOpenPdfModal', 'pdfModal', 'pdfTitle', 'pdfSubtitle', 'pdfExamDate', 'pdfSubject',
      'pdfDuration', 'pdfTotalScore', 'pdfNotice', 'pdfTemplate', 'pdfIncludeSolutions',
      'scopeSelected', 'scopeSelectedCount', 'scopeAll', 'pdfResult', 'btnGeneratePdf',
    ].forEach((id) => { els[id] = document.getElementById(id); });

    bindFilterEvents();
    bindListEvents();
    bindPdfEvents();

    loadStats();
    loadChapters('');
    loadList();
  }

  // ================================================================ 统计

  /** 加载顶部统计(总数 + 科目分布) */
  async function loadStats() {
    try {
      const resp = await apiFetch('/api/error_book/stats');
      const d = resp.data || {};
      els.statTotal.textContent = d.total != null ? d.total : 0;
      renderSubjectStats(d.by_subject || {});
    } catch (err) {
      els.statTotal.textContent = '-';
      els.statBySubject.innerHTML = '<span class="text-muted small">统计加载失败</span>';
      console.warn('加载错题统计失败:', err);
    }
  }

  /** 渲染科目分布徽章(点击可按该科目筛选) */
  function renderSubjectStats(bySubject) {
    const items = Object.entries(bySubject);
    if (!items.length) {
      els.statBySubject.innerHTML = '<span class="text-muted small">暂无错题</span>';
      return;
    }
    els.statBySubject.innerHTML = items.map(([subject, count]) => `
      <span class="subject-dist-item" data-subject="${escapeHtml(subject)}" title="点击筛选该科目">
        ${escapeHtml(subject)} <span class="dist-count">${Number(count) || 0}</span>
      </span>`).join('');
    els.statBySubject.querySelectorAll('.subject-dist-item').forEach((el) => {
      el.addEventListener('click', () => {
        els.filterSubject.value = el.dataset.subject;
        onSubjectChange();
      });
    });
  }

  // ================================================================ 筛选

  /** 绑定筛选栏事件 */
  function bindFilterEvents() {
    els.filterSubject.addEventListener('change', onSubjectChange);
    els.filterChapter.addEventListener('change', () => {
      state.filters.chapter = els.filterChapter.value;
      reloadFromFirstPage();
    });
    els.filterDifficulty.addEventListener('change', () => {
      state.filters.difficulty = els.filterDifficulty.value;
      reloadFromFirstPage();
    });
    els.filterSource.addEventListener('input', debounce(() => {
      state.filters.source = els.filterSource.value.trim();
      reloadFromFirstPage();
    }, 400));
    els.filterSearch.addEventListener('input', debounce(() => {
      state.filters.search = els.filterSearch.value.trim();
      reloadFromFirstPage();
    }, 400));
    els.btnResetFilters.addEventListener('click', resetFilters);
    els.perPageSelect.addEventListener('change', () => {
      state.perPage = parseInt(els.perPageSelect.value, 10) || 20;
      reloadFromFirstPage();
    });
  }

  /** 课程变化:联动章节下拉并刷新列表 */
  function onSubjectChange() {
    state.filters.subject = els.filterSubject.value;
    state.filters.chapter = '';
    loadChapters(state.filters.subject);
    reloadFromFirstPage();
  }

  /** 重置全部筛选条件 */
  function resetFilters() {
    state.filters = { subject: '', chapter: '', difficulty: '', source: '', search: '' };
    els.filterSubject.value = '';
    els.filterDifficulty.value = '';
    els.filterSource.value = '';
    els.filterSearch.value = '';
    loadChapters('');
    reloadFromFirstPage();
  }

  /** 从题目模块的 filters 接口联动加载章节下拉(失败时静默降级) */
  async function loadChapters(subject) {
    els.filterChapter.innerHTML = '<option value="">全部章节</option>';
    try {
      const resp = await apiFetch('/api/questions/filters' + buildQuery({ subject }));
      const chapters = (resp.data && resp.data.chapters) || [];
      els.filterChapter.innerHTML = '<option value="">全部章节</option>'
        + chapters.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    } catch (err) {
      console.warn('加载章节列表失败:', err);
    }
  }

  /** 回到第一页并刷新 */
  function reloadFromFirstPage() {
    state.page = 1;
    loadList();
  }

  // ================================================================ 列表

  /** 加载错题列表 */
  async function loadList(isRetry) {
    if (!isRetry) showListLoading();
    const seq = ++listSeq;
    try {
      const resp = await apiFetch('/api/error_book' + buildQuery({
        subject: state.filters.subject,
        chapter: state.filters.chapter,
        difficulty: state.filters.difficulty,
        source: state.filters.source,
        search: state.filters.search,
        page: state.page,
        per_page: state.perPage,
      }));
      if (seq !== listSeq) return;   // 已有更新的请求发出,丢弃这次过期响应
      const d = resp.data || {};
      state.entries = d.entries || [];
      state.total = d.total || 0;
      state.pages = d.pages || 0;
      // 删除后当前页可能越界:回退到最后一页重新加载(仅重试一次)
      if (!state.entries.length && state.total > 0 && state.page > 1 && !isRetry) {
        state.page = Math.max(1, state.pages);
        return loadList(true);
      }
      renderList();
      renderPagination();
      renderSummary();
      updateBatchToolbar();
    } catch (err) {
      if (seq !== listSeq) return;
      showToast(err.message || '加载错题列表失败', 'danger');
      renderListError();
    }
  }

  /** 列表加载中占位 */
  function showListLoading() {
    els.emptyState.style.display = 'none';
    els.entryList.innerHTML =
      '<div class="text-center text-muted py-5">' +
      '<div class="spinner-border text-primary" role="status"></div>' +
      '<div class="mt-2">加载中...</div></div>';
  }

  /** 列表加载失败提示(附重试按钮) */
  function renderListError() {
    els.emptyState.style.display = 'none';
    els.listSummary.textContent = '';
    els.entryList.innerHTML =
      '<div class="text-center text-muted py-5">' +
      '<i class="fa-solid fa-triangle-exclamation fa-2x mb-2 text-warning d-block"></i>' +
      '<div class="mb-2">加载失败,请稍后重试</div>' +
      '<button type="button" class="btn btn-sm btn-outline-primary btn-retry-list">' +
      '<i class="fa-solid fa-rotate-right me-1"></i>重试</button></div>';
  }

  /** 渲染列表 */
  function renderList() {
    const hasData = state.entries.length > 0;
    els.emptyState.style.display = hasData ? 'none' : '';
    els.entryList.innerHTML = hasData ? state.entries.map(entryCardHtml).join('') : '';
    if (hasData) {
      typesetMath(els.entryList);
    }
    syncCheckAll();
  }

  /** 单条错题卡片 HTML */
  function entryCardHtml(entry) {
    const q = entry.question || {};
    const qid = Number(q.id);
    const isSelected = state.selected.has(qid);
    const latex = q.question_latex
      ? escapeHtml(q.question_latex)
      : '<span class="text-muted fst-italic">(本题内容为图片,请打开预览查看)</span>';
    const tags = (q.tags && q.tags.length) ? `<div class="mb-2">${tagBadges(q.tags)}</div>` : '';
    return `
    <div class="question-card ${isSelected ? 'selected' : ''}" data-qid="${qid}">
      <div class="d-flex justify-content-between align-items-start mb-2 gap-2">
        <div class="d-flex align-items-center gap-2 flex-wrap">
          <input type="checkbox" class="form-check-input entry-checkbox mt-0" data-qid="${qid}"
                 ${isSelected ? 'checked' : ''} aria-label="选择题目 ${qid}">
          <span class="fw-bold">#${qid}</span>
          <span class="badge bg-secondary">${escapeHtml(q.subject)}</span>
          ${q.chapter ? `<span class="badge bg-light text-dark border">${escapeHtml(q.chapter)}</span>` : ''}
          ${difficultyBadge(q.difficulty)}
          ${q.source ? `<span class="small text-muted"><i class="fa-solid fa-building-columns me-1"></i>${escapeHtml(q.source)}</span>` : ''}
        </div>
        <div class="btn-group btn-group-sm flex-shrink-0">
          <button type="button" class="btn btn-outline-primary btn-preview" data-qid="${qid}" title="快速预览">
            <i class="fa-solid fa-eye"></i>
          </button>
          <button type="button" class="btn btn-outline-danger btn-remove" data-qid="${qid}" title="移出错题本">
            <i class="fa-solid fa-trash-can"></i>
          </button>
        </div>
      </div>
      <div class="latex-content mb-2">${latex}</div>
      ${tags}
      <div class="entry-meta mb-2"><i class="fa-regular fa-clock me-1"></i>加入时间:${escapeHtml(formatDate(entry.created_at, true))}</div>
      <div class="notes-area" data-qid="${qid}">${notesBoxHtml(entry)}</div>
    </div>`;
  }

  /** 备注展示块 HTML */
  function notesBoxHtml(entry) {
    const qid = Number(entry.question_id);
    const notesHtml = entry.notes
      ? escapeHtml(entry.notes).replace(/\n/g, '<br>')
      : '<span class="notes-empty">暂无备注,点击右侧"编辑"添加</span>';
    return `
      <div class="notes-box d-flex justify-content-between align-items-start gap-2">
        <div class="flex-grow-1">
          <i class="fa-solid fa-pen-nib me-1 text-warning"></i>
          <span class="notes-text">${notesHtml}</span>
        </div>
        <button type="button" class="btn btn-sm btn-link p-0 flex-shrink-0 btn-edit-notes" data-qid="${qid}">编辑</button>
      </div>`;
  }

  /** 列表汇总文案 */
  function renderSummary() {
    els.listSummary.textContent = state.total
      ? `共 ${state.total} 题,第 ${state.page}/${Math.max(state.pages, 1)} 页`
      : '共 0 题';
  }

  /** 按 question_id 在当前页数据中查找条目 */
  function findEntry(qid) {
    return state.entries.find((e) => Number(e.question_id) === Number(qid)) || null;
  }

  // ================================================================ 列表交互(事件委托)

  /** 绑定列表区域与批量操作事件 */
  function bindListEvents() {
    els.entryList.addEventListener('click', (event) => {
      const retryBtn = event.target.closest('.btn-retry-list');
      if (retryBtn) { loadList(); return; }
      const previewBtn = event.target.closest('.btn-preview');
      if (previewBtn) { openPreview(Number(previewBtn.dataset.qid)); return; }
      const removeBtn = event.target.closest('.btn-remove');
      if (removeBtn) { removeSingle(Number(removeBtn.dataset.qid)); return; }
      const editBtn = event.target.closest('.btn-edit-notes');
      if (editBtn) { startEditNotes(Number(editBtn.dataset.qid)); return; }
      const saveBtn = event.target.closest('.btn-save-notes');
      if (saveBtn) { saveNotes(Number(saveBtn.dataset.qid)); return; }
      const cancelBtn = event.target.closest('.btn-cancel-notes');
      if (cancelBtn) { cancelEditNotes(Number(cancelBtn.dataset.qid)); }
    });

    els.entryList.addEventListener('change', (event) => {
      const checkbox = event.target.closest('.entry-checkbox');
      if (!checkbox) return;
      toggleSelect(Number(checkbox.dataset.qid), checkbox.checked);
    });

    els.checkAll.addEventListener('change', () => {
      const checked = els.checkAll.checked;
      state.entries.forEach((entry) => {
        const qid = Number(entry.question_id);
        if (checked) state.selected.add(qid);
        else state.selected.delete(qid);
      });
      els.entryList.querySelectorAll('.entry-checkbox').forEach((cb) => {
        cb.checked = checked;
        cb.closest('.question-card').classList.toggle('selected', checked);
      });
      updateBatchToolbar();
    });

    els.btnClearSelection.addEventListener('click', clearSelection);
    els.btnBatchRemove.addEventListener('click', batchRemove);
    els.btnToggleSolution.addEventListener('click', toggleSolution);
  }

  /** 勾选/取消勾选单题 */
  function toggleSelect(qid, checked) {
    if (checked) state.selected.add(qid);
    else state.selected.delete(qid);
    const card = els.entryList.querySelector(`.question-card[data-qid="${qid}"]`);
    if (card) card.classList.toggle('selected', checked);
    syncCheckAll();
    updateBatchToolbar();
  }

  /** 同步"全选本页"复选框状态 */
  function syncCheckAll() {
    const total = state.entries.length;
    const selectedOnPage = state.entries
      .filter((e) => state.selected.has(Number(e.question_id))).length;
    els.checkAll.checked = total > 0 && selectedOnPage === total;
    els.checkAll.indeterminate = selectedOnPage > 0 && selectedOnPage < total;
  }

  /** 清空所有选择 */
  function clearSelection() {
    state.selected.clear();
    els.entryList.querySelectorAll('.entry-checkbox').forEach((cb) => {
      cb.checked = false;
      cb.closest('.question-card').classList.remove('selected');
    });
    syncCheckAll();
    updateBatchToolbar();
  }

  /** 更新批量工具栏显隐与计数 */
  function updateBatchToolbar() {
    const count = state.selected.size;
    els.selectedCount.textContent = count;
    els.batchToolbar.style.display = count > 0 ? '' : 'none';
  }

  // ================================================================ 移出

  /** 移出单题 */
  async function removeSingle(qid) {
    if (!window.confirm(`确定将题目 #${qid} 移出错题本吗?`)) return;
    try {
      await apiFetch('/api/error_book/remove', { method: 'POST', body: { question_id: qid } });
      state.selected.delete(qid);
      showToast('已移出错题本', 'success');
      loadStats();
      loadList();
    } catch (err) {
      showToast(err.message || '移出失败', 'danger');
    }
  }

  /** 批量移出已勾选题目 */
  async function batchRemove() {
    const ids = Array.from(state.selected);
    if (!ids.length) {
      showToast('请先勾选要移出的题目', 'warning');
      return;
    }
    if (!window.confirm(`确定将已选 ${ids.length} 题移出错题本吗?`)) return;
    try {
      const resp = await apiFetch('/api/error_book/remove', {
        method: 'POST', body: { question_ids: ids },
      });
      const removed = (resp.data && resp.data.removed) || 0;
      state.selected.clear();
      showToast(`已移出 ${removed} 题`, 'success');
      loadStats();
      loadList();
    } catch (err) {
      showToast(err.message || '批量移出失败', 'danger');
    }
  }

  // ================================================================ 备注内联编辑

  /** 进入备注编辑态 */
  function startEditNotes(qid) {
    const entry = findEntry(qid);
    const area = els.entryList.querySelector(`.notes-area[data-qid="${qid}"]`);
    if (!entry || !area) return;
    area.innerHTML = `
      <textarea class="form-control form-control-sm notes-input" rows="3" maxlength="5000"
                placeholder="记录错因、思路、易错点...">${escapeHtml(entry.notes || '')}</textarea>
      <div class="mt-1 d-flex gap-2">
        <button type="button" class="btn btn-sm btn-primary btn-save-notes" data-qid="${qid}">
          <i class="fa-solid fa-check me-1"></i>保存
        </button>
        <button type="button" class="btn btn-sm btn-outline-secondary btn-cancel-notes" data-qid="${qid}">取消</button>
      </div>`;
    area.querySelector('.notes-input').focus();
  }

  /** 保存备注 */
  async function saveNotes(qid) {
    const entry = findEntry(qid);
    const area = els.entryList.querySelector(`.notes-area[data-qid="${qid}"]`);
    if (!entry || !area) return;
    const input = area.querySelector('.notes-input');
    const notes = input ? input.value.trim() : '';
    try {
      await apiFetch('/api/error_book/update_notes', {
        method: 'POST', body: { question_id: qid, notes },
      });
      entry.notes = notes;
      area.innerHTML = notesBoxHtml(entry);
      typesetMath(area);
      showToast('备注已保存', 'success');
    } catch (err) {
      showToast(err.message || '保存备注失败', 'danger');
    }
  }

  /** 取消备注编辑,恢复展示态 */
  function cancelEditNotes(qid) {
    const entry = findEntry(qid);
    const area = els.entryList.querySelector(`.notes-area[data-qid="${qid}"]`);
    if (entry && area) {
      area.innerHTML = notesBoxHtml(entry);
      typesetMath(area);
    }
  }

  // ================================================================ 快速预览

  /** 打开题目快速预览 Modal */
  function openPreview(qid) {
    const entry = findEntry(qid);
    if (!entry || !entry.question) return;
    const q = entry.question;

    els.previewInfo.innerHTML = `
      <div class="d-flex align-items-center gap-2 flex-wrap mb-1">
        <span class="fw-bold">#${Number(q.id)}</span>
        <span class="badge bg-secondary">${escapeHtml(q.subject)}</span>
        ${q.chapter ? `<span class="badge bg-light text-dark border">${escapeHtml(q.chapter)}</span>` : ''}
        ${difficultyBadge(q.difficulty)}
      </div>
      ${q.source ? `<div class="small text-muted mb-1"><i class="fa-solid fa-building-columns me-1"></i>来源:${escapeHtml(q.source)}</div>` : ''}
      ${(q.tags && q.tags.length) ? `<div class="mb-1">${tagBadges(q.tags)}</div>` : ''}
      <div class="small text-muted">加入错题本:${escapeHtml(formatDate(entry.created_at, true))}</div>`;

    els.previewQuestion.innerHTML = q.question_latex
      ? escapeHtml(q.question_latex)
      : '<span class="text-muted fst-italic">(无文字内容)</span>';
    els.previewQuestionImage.innerHTML = mediaHtml(q.question_image_url, '题目');

    els.previewSolution.innerHTML = q.solution_latex
      ? escapeHtml(q.solution_latex)
      : '<span class="text-muted fst-italic">(暂无文字解答)</span>';
    els.previewSolutionImage.innerHTML = mediaHtml(q.solution_image_url, '解答');

    // 每次打开都先收起解答
    els.previewSolutionWrap.style.display = 'none';
    els.btnToggleSolution.innerHTML = '<i class="fa-solid fa-lightbulb me-1"></i>查看答案';

    typesetMath(els.previewModal.querySelector('.modal-body'));
    bootstrap.Modal.getOrCreateInstance(els.previewModal).show();
  }

  /** 展开/收起解答区块 */
  function toggleSolution() {
    const hidden = els.previewSolutionWrap.style.display === 'none';
    els.previewSolutionWrap.style.display = hidden ? '' : 'none';
    els.btnToggleSolution.innerHTML = hidden
      ? '<i class="fa-solid fa-eye-slash me-1"></i>收起答案'
      : '<i class="fa-solid fa-lightbulb me-1"></i>查看答案';
    if (hidden) typesetMath(els.previewSolutionWrap);
  }

  /** 图片/PDF 附件 HTML(图片直接展示,PDF 给链接) */
  function mediaHtml(url, label) {
    if (!url) return '';
    if (/\.pdf(\?|$)/i.test(url)) {
      return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-secondary">
        <i class="fa-solid fa-file-pdf me-1"></i>查看${escapeHtml(label)}附件(PDF)</a>`;
    }
    return `<img src="${escapeHtml(url)}" alt="${escapeHtml(label)}图片" class="question-detail-image">`;
  }

  // ================================================================ 分页

  /** 渲染分页组件 */
  function renderPagination() {
    els.pagination.innerHTML = '';
    if (state.pages <= 1) return;

    const addItem = (label, page, { disabled = false, active = false, ellipsis = false } = {}) => {
      const li = document.createElement('li');
      li.className = `page-item${disabled ? ' disabled' : ''}${active ? ' active' : ''}`;
      if (ellipsis) {
        li.innerHTML = '<span class="page-link">…</span>';
      } else {
        const a = document.createElement('a');
        a.className = 'page-link';
        a.href = '#';
        a.innerHTML = label;
        a.addEventListener('click', (event) => {
          event.preventDefault();
          if (disabled || active) return;
          state.page = page;
          loadList();
        });
        li.appendChild(a);
      }
      els.pagination.appendChild(li);
    };

    addItem('<i class="fa-solid fa-angle-left"></i>', state.page - 1, { disabled: state.page <= 1 });
    pageWindow(state.page, state.pages).forEach((p) => {
      if (p === '...') addItem('', 0, { ellipsis: true });
      else addItem(String(p), p, { active: p === state.page });
    });
    addItem('<i class="fa-solid fa-angle-right"></i>', state.page + 1, { disabled: state.page >= state.pages });
  }

  /** 生成带省略号的页码序列,如 [1, '...', 4, 5, 6, '...', 20] */
  function pageWindow(current, total) {
    const pages = [];
    for (let p = 1; p <= total; p++) {
      if (p === 1 || p === total || Math.abs(p - current) <= 2) {
        pages.push(p);
      } else if (pages[pages.length - 1] !== '...') {
        pages.push('...');
      }
    }
    return pages;
  }

  // ================================================================ PDF 生成

  /** 绑定 PDF 配置 Modal 事件 */
  function bindPdfEvents() {
    els.btnOpenPdfModal.addEventListener('click', openPdfModal);
    els.btnGeneratePdf.addEventListener('click', handleGeneratePdf);
  }

  /** 打开 PDF 配置 Modal */
  function openPdfModal() {
    // 默认考试日期为今天(用本地日期,避免 toISOString 的 UTC 偏移导致 JST 上午显示前一天)
    if (!els.pdfExamDate.value) {
      const d = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      els.pdfExamDate.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }
    // 勾选范围计数;无勾选时禁用该选项
    const count = state.selected.size;
    els.scopeSelectedCount.textContent = count;
    els.scopeSelected.disabled = count === 0;
    if (count === 0 && els.scopeSelected.checked) {
      els.scopeAll.checked = true;
    }
    els.pdfResult.style.display = 'none';
    els.pdfResult.innerHTML = '';
    bootstrap.Modal.getOrCreateInstance(els.pdfModal).show();
  }

  /** 提交生成 PDF */
  async function handleGeneratePdf() {
    const config = {
      title: els.pdfTitle.value.trim(),
      subtitle: els.pdfSubtitle.value.trim(),
      exam_date: els.pdfExamDate.value,
      subject: els.pdfSubject.value,
      duration: els.pdfDuration.value.trim(),
      total_score: els.pdfTotalScore.value.trim(),
      notice: els.pdfNotice.value.trim(),
      template: els.pdfTemplate.value,
      include_solutions: els.pdfIncludeSolutions.checked,
    };
    if (!config.title) {
      showToast('请填写试卷标题', 'warning');
      els.pdfTitle.focus();
      return;
    }
    const scopeInput = document.querySelector('input[name="pdfScope"]:checked');
    const scope = scopeInput ? scopeInput.value : 'all';
    if (scope === 'selected' && !state.selected.size) {
      showToast('尚未勾选任何题目', 'warning');
      return;
    }

    const btn = els.btnGeneratePdf;
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>生成中...';
    try {
      if (scope === 'selected') {
        config.question_ids = Array.from(state.selected);
      } else if (scope === 'filtered') {
        config.question_ids = await collectFilteredIds();
        if (!config.question_ids.length) {
          showToast('当前筛选结果为空,无法生成', 'warning');
          return;
        }
      }
      const resp = await apiFetch('/api/error_book/generate_pdf', { method: 'POST', body: config });
      const d = resp.data || {};
      if (d.engine_missing) {
        showToast(resp.message || '服务器未安装 LaTeX 引擎,已生成 .tex 源文件', 'warning', 6000);
        showPdfResult(d.tex_url, d.filename, true);
      } else {
        showToast(resp.message || '试卷 PDF 生成成功', 'success');
        showPdfResult(d.pdf_url, d.filename, false);
      }
    } catch (err) {
      showToast(err.message || 'PDF 生成失败', 'danger', 6000);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }

  /** 收集当前筛选条件下的全部 question_id(逐页拉取,最多 50 页 x 100 条) */
  async function collectFilteredIds() {
    const ids = [];
    let page = 1;
    while (page <= 50) {
      const resp = await apiFetch('/api/error_book' + buildQuery({
        subject: state.filters.subject,
        chapter: state.filters.chapter,
        difficulty: state.filters.difficulty,
        source: state.filters.source,
        search: state.filters.search,
        page,
        per_page: 100,
      }));
      const d = resp.data || {};
      (d.entries || []).forEach((e) => ids.push(Number(e.question_id)));
      if (page >= (d.pages || 0)) break;
      page += 1;
    }
    return ids;
  }

  /** 在 Modal 内展示生成结果的下载链接 */
  function showPdfResult(url, filename, isTex) {
    if (!url) return;
    els.pdfResult.className = `alert mt-3 mb-0 pdf-result-area alert-${isTex ? 'warning' : 'success'}`;
    els.pdfResult.innerHTML = `
      <div class="mb-2">
        <i class="fa-solid ${isTex ? 'fa-triangle-exclamation' : 'fa-circle-check'} me-1"></i>
        ${isTex ? '服务器未安装 LaTeX 引擎,已生成 .tex 源文件,可下载后本地编译:' : '试卷生成成功,点击下载:'}
      </div>
      <a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="btn btn-sm btn-${isTex ? 'warning' : 'success'}">
        <i class="fa-solid fa-download me-1"></i>${escapeHtml(filename || '下载文件')}
      </a>`;
    els.pdfResult.style.display = '';
  }
})();
