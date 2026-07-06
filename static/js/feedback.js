/**
 * 意见反馈页脚本。
 *
 * 功能:提交反馈表单、状态 tab 筛选(带计数徽章)、重置筛选、
 *       管理员标记状态/填写回复、删除(本人或管理员)。
 * 依赖:utils.js(apiFetch/buildQuery/escapeHtml/typesetMath/formatDate)、toast.js(showToast)。
 */
(function () {
  'use strict';

  const cfg = window.PAGE_CONFIG || { isAdmin: false, userId: 0 };

  const state = {
    status: '全部',   // 当前筛选状态
    feedbacks: [],    // 当前列表数据
  };

  let loadSeq = 0;    // 请求序号:仅渲染最新一次请求的响应,避免过期响应覆盖
  let listEl = null;
  let tabsEl = null;
  let statusModal = null;   // Bootstrap Modal 实例(仅管理员)
  let currentFid = null;    // 处理弹窗对应的反馈 id

  document.addEventListener('DOMContentLoaded', init);

  /** 页面初始化:绑定事件并加载列表 */
  function init() {
    listEl = document.getElementById('feedbackList');
    tabsEl = document.getElementById('feedbackTabs');

    document.getElementById('feedbackForm').addEventListener('submit', onSubmitForm);
    document.getElementById('resetFilterBtn').addEventListener('click', function () {
      setStatus('全部');
    });

    tabsEl.addEventListener('click', function (e) {
      const link = e.target.closest('.nav-link');
      if (!link) return;
      e.preventDefault();
      setStatus(link.dataset.status);
    });

    // 列表操作按钮统一事件委托
    listEl.addEventListener('click', onListClick);

    const modalEl = document.getElementById('statusModal');
    if (modalEl && window.bootstrap) {
      statusModal = new bootstrap.Modal(modalEl);
      document.getElementById('statusSaveBtn').addEventListener('click', saveStatus);
    }

    loadFeedbacks();
  }

  /** 切换状态筛选并刷新列表 */
  function setStatus(status) {
    state.status = status || '全部';
    tabsEl.querySelectorAll('.nav-link').forEach(function (link) {
      link.classList.toggle('active', link.dataset.status === state.status);
    });
    loadFeedbacks();
  }

  /** 拉取反馈列表(带状态筛选)并渲染 */
  async function loadFeedbacks() {
    const seq = ++loadSeq;
    listEl.innerHTML =
      '<div class="text-center text-muted py-5">' +
      '<div class="spinner-border text-primary" role="status"></div>' +
      '<div class="mt-2">加载中...</div></div>';
    try {
      const query = buildQuery({ status: state.status === '全部' ? '' : state.status });
      const resp = await apiFetch('/api/feedback' + query);
      if (seq !== loadSeq) return;  // 已有更新的请求发出,丢弃这次过期响应
      const data = resp.data || {};
      state.feedbacks = data.feedbacks || [];
      renderCounts(data.counts || {});
      renderList();
    } catch (err) {
      if (seq !== loadSeq) return;
      listEl.innerHTML =
        '<div class="text-center text-muted py-5">' +
        '<i class="fa-solid fa-triangle-exclamation fa-2x mb-2 text-warning"></i>' +
        '<div>' + escapeHtml(err.message || '加载失败') + '</div></div>';
      showToast(err.message || '加载反馈列表失败', 'danger');
    }
  }

  /** 更新 tab 上的计数徽章 */
  function renderCounts(counts) {
    document.getElementById('countAll').textContent = counts['全部'] || 0;
    document.getElementById('countPending').textContent = counts['待处理'] || 0;
    document.getElementById('countDone').textContent = counts['已处理'] || 0;
  }

  /** 渲染反馈列表 */
  function renderList() {
    if (!state.feedbacks.length) {
      listEl.innerHTML =
        '<div class="text-center text-muted py-5">' +
        '<i class="fa-regular fa-folder-open fa-2x mb-2"></i>' +
        '<div>暂无反馈</div></div>';
      return;
    }
    listEl.innerHTML = state.feedbacks.map(renderItem).join('');
    // 反馈内容可能包含 LaTeX 公式,渲染后重排
    typesetMath(listEl);
  }

  /** 状态徽章:待处理黄色 / 已处理绿色 */
  function statusBadge(status) {
    return status === '已处理'
      ? '<span class="badge bg-success">已处理</span>'
      : '<span class="badge bg-warning text-dark">待处理</span>';
  }

  /** 单条反馈 HTML */
  function renderItem(fb) {
    const metaParts = [
      '<span><i class="fa-regular fa-clock me-1"></i>' + escapeHtml(formatDate(fb.created_at, true)) + '</span>',
    ];
    if (cfg.isAdmin && fb.username) {
      metaParts.push('<span><i class="fa-solid fa-user me-1"></i>' + escapeHtml(fb.username) + '</span>');
    }

    const replyHtml = fb.reply
      ? '<div class="feedback-reply"><span class="reply-label">' +
        '<i class="fa-solid fa-reply me-1"></i>管理员回复:</span>' + escapeHtml(fb.reply) + '</div>'
      : '';

    const buttons = [];
    if (cfg.isAdmin) {
      buttons.push(
        '<button type="button" class="btn btn-sm btn-outline-primary" data-action="process">' +
        '<i class="fa-solid fa-clipboard-check me-1"></i>处理</button>');
      const toggleLabel = fb.status === '已处理' ? '标记待处理' : '标记已处理';
      buttons.push(
        '<button type="button" class="btn btn-sm btn-outline-secondary" data-action="toggle">' +
        '<i class="fa-solid fa-arrows-rotate me-1"></i>' + toggleLabel + '</button>');
    }
    if (cfg.isAdmin || fb.user_id === cfg.userId) {
      buttons.push(
        '<button type="button" class="btn btn-sm btn-outline-danger" data-action="delete">' +
        '<i class="fa-solid fa-trash-can me-1"></i>删除</button>');
    }

    return (
      '<div class="feedback-item" data-id="' + fb.id + '">' +
      '  <div class="d-flex justify-content-between align-items-start gap-2 flex-wrap">' +
      '    <div class="feedback-title">' + escapeHtml(fb.title) + '</div>' +
      '    ' + statusBadge(fb.status) +
      '  </div>' +
      (fb.content ? '<div class="feedback-content">' + escapeHtml(fb.content) + '</div>' : '') +
      replyHtml +
      '  <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mt-2">' +
      '    <div class="feedback-meta">' + metaParts.join('') + '</div>' +
      '    <div class="d-flex gap-2">' + buttons.join('') + '</div>' +
      '  </div>' +
      '</div>');
  }

  /** 列表内按钮事件委托 */
  function onListClick(e) {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const item = btn.closest('.feedback-item');
    if (!item) return;
    const fid = parseInt(item.dataset.id, 10);
    const fb = state.feedbacks.find(function (f) { return f.id === fid; });
    if (!fb) return;

    const action = btn.dataset.action;
    if (action === 'delete') {
      deleteFeedback(fb, btn);
    } else if (action === 'process') {
      openStatusModal(fb);
    } else if (action === 'toggle') {
      toggleStatus(fb, btn);
    }
  }

  /** 提交反馈表单 */
  async function onSubmitForm(e) {
    e.preventDefault();
    const titleInput = document.getElementById('fbTitle');
    const contentInput = document.getElementById('fbContent');
    const submitBtn = document.getElementById('fbSubmitBtn');

    const title = titleInput.value.trim();
    if (!title) {
      titleInput.classList.add('is-invalid');
      titleInput.focus();
      return;
    }
    titleInput.classList.remove('is-invalid');

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>提交中...';
    try {
      const resp = await apiFetch('/api/feedback', {
        method: 'POST',
        body: { title: title, content: contentInput.value.trim() },
      });
      showToast(resp.message || '反馈提交成功', 'success');
      titleInput.value = '';
      contentInput.value = '';
      loadFeedbacks();
    } catch (err) {
      showToast(err.message || '提交失败,请稍后重试', 'danger');
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<i class="fa-solid fa-paper-plane me-1"></i>提交反馈';
    }
  }

  /** 打开管理员处理弹窗(预填状态与回复) */
  function openStatusModal(fb) {
    if (!statusModal) return;
    currentFid = fb.id;
    document.getElementById('statusModalInfo').textContent = '#' + fb.id + ' ' + fb.title;
    document.getElementById('statusSelect').value = fb.status === '已处理' ? '已处理' : '待处理';
    document.getElementById('replyText').value = fb.reply || '';
    statusModal.show();
  }

  /** 保存处理弹窗:状态 + 回复 */
  async function saveStatus() {
    if (currentFid == null) return;
    const saveBtn = document.getElementById('statusSaveBtn');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>保存中...';
    try {
      const resp = await apiFetch('/api/feedback/' + currentFid + '/status', {
        method: 'POST',
        body: {
          status: document.getElementById('statusSelect').value,
          reply: document.getElementById('replyText').value.trim(),
        },
      });
      showToast(resp.message || '已更新', 'success');
      statusModal.hide();
      loadFeedbacks();
    } catch (err) {
      showToast(err.message || '更新失败,请稍后重试', 'danger');
    } finally {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<i class="fa-solid fa-check me-1"></i>保存';
    }
  }

  /** 快捷切换状态(不改动已有回复) */
  async function toggleStatus(fb, btn) {
    const newStatus = fb.status === '已处理' ? '待处理' : '已处理';
    btn.disabled = true;
    try {
      const resp = await apiFetch('/api/feedback/' + fb.id + '/status', {
        method: 'POST',
        body: { status: newStatus },
      });
      showToast(resp.message || '已标记为' + newStatus, 'success');
      loadFeedbacks();
    } catch (err) {
      btn.disabled = false;
      showToast(err.message || '操作失败,请稍后重试', 'danger');
    }
  }

  /** 删除反馈(本人或管理员) */
  async function deleteFeedback(fb, btn) {
    if (!window.confirm('确定删除反馈「' + fb.title + '」吗?此操作不可恢复。')) return;
    btn.disabled = true;
    try {
      const resp = await apiFetch('/api/feedback/' + fb.id, { method: 'DELETE' });
      showToast(resp.message || '已删除', 'success');
      loadFeedbacks();
    } catch (err) {
      btn.disabled = false;
      showToast(err.message || '删除失败,请稍后重试', 'danger');
    }
  }
})();
