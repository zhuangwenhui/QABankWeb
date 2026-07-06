/**
 * 管理总览页脚本。
 *
 * 一次性拉取 /api/overview/stats,渲染:
 *   4 张统计卡片、按课程/难度题数分布(纯 CSS 进度条)、
 *   近 14 天查看趋势(纯 CSS 柱状图)、最常查看 Top10 表格、
 *   全体用户错题按科目分布、最近新增题目。
 * 依赖:utils.js(apiFetch/escapeHtml/typesetMath/difficultyBadge/tagBadges/formatDate)、toast.js。
 */
(function () {
  'use strict';

  const TREND_BAR_MAX_PX = 150; // 趋势图柱条最大高度(px)

  document.addEventListener('DOMContentLoaded', function () {
    init();
    initUserManage();
  });

  /** 拉取统计数据并渲染各区块 */
  async function init() {
    try {
      const resp = await apiFetch('/api/overview/stats');
      const d = resp.data || {};
      renderStatCards(d);
      renderDistribution(document.getElementById('subjectDist'), d.by_subject || {}, 'bg-primary');
      renderDifficultyDist(d.by_difficulty || {});
      renderTrend(d.views_last_14_days || []);
      renderTopViewed(d.top_viewed || []);
      renderDistribution(document.getElementById('errorDist'), d.error_by_subject || {}, 'bg-danger');
      renderRecent(d.recent_questions || []);
    } catch (err) {
      showToast(err.message || '统计数据加载失败', 'danger');
      const failHtml = '<div class="loading-block"><i class="fa-solid fa-triangle-exclamation me-1 text-warning"></i>加载失败</div>';
      ['subjectDist', 'difficultyDist', 'viewTrend', 'errorDist', 'recentQuestions'].forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.innerHTML = failHtml;
      });
      const tbody = document.getElementById('topViewedBody');
      if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="loading-block">加载失败</td></tr>';
    }
  }

  /** 顶部 4 张统计卡片 */
  function renderStatCards(d) {
    setText('statQuestions', d.question_total);
    setText('statUsers', d.user_total);
    setText('statErrors', d.error_book_total);
    setText('statPending', d.feedback_pending);
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value != null ? value : 0;
  }

  /** 单行分布条 HTML */
  function distRow(label, count, max, barClass) {
    const pct = max > 0 ? Math.round((count / max) * 100) : 0;
    return (
      '<div class="dist-row">' +
      '  <span class="dist-label" title="' + escapeHtml(label) + '">' + escapeHtml(label) + '</span>' +
      '  <div class="progress"><div class="progress-bar ' + barClass + '" role="progressbar"' +
      '       style="width:' + pct + '%"></div></div>' +
      '  <span class="dist-count">' + Number(count) + '</span>' +
      '</div>');
  }

  /** 通用分布(课程题数 / 错题科目):按数量降序 */
  function renderDistribution(container, mapObj, barClass) {
    if (!container) return;
    const entries = Object.entries(mapObj).sort(function (a, b) { return b[1] - a[1]; });
    if (!entries.length) {
      container.innerHTML = '<div class="loading-block">暂无数据</div>';
      return;
    }
    const max = Math.max.apply(null, entries.map(function (e) { return e[1]; }).concat([1]));
    container.innerHTML = entries.map(function (e) {
      return distRow(e[0], e[1], max, barClass);
    }).join('');
  }

  /** 难度分布:固定顺序 简单/中等/困难,颜色对应绿/黄/红 */
  function renderDifficultyDist(mapObj) {
    const container = document.getElementById('difficultyDist');
    if (!container) return;
    const order = [
      ['简单', 'bg-success'],
      ['中等', 'bg-warning'],
      ['困难', 'bg-danger'],
    ];
    const counts = order.map(function (o) { return Number(mapObj[o[0]] || 0); });
    const max = Math.max.apply(null, counts.concat([1]));
    container.innerHTML = order.map(function (o, i) {
      return distRow(o[0], counts[i], max, o[1]);
    }).join('');
  }

  /** 近 14 天查看趋势:纯 CSS 柱状图 */
  function renderTrend(days) {
    const container = document.getElementById('viewTrend');
    if (!container) return;
    if (!days.length) {
      container.innerHTML = '<div class="loading-block">暂无查看记录</div>';
      return;
    }
    const max = Math.max.apply(null, days.map(function (d) { return d.count; }).concat([1]));
    const cols = days.map(function (d) {
      const h = Math.max(2, Math.round((d.count / max) * TREND_BAR_MAX_PX));
      return (
        '<div class="trend-col" title="' + escapeHtml(d.date) + ':' + Number(d.count) + ' 次">' +
        '  <div class="trend-count">' + Number(d.count) + '</div>' +
        '  <div class="trend-bar" style="height:' + h + 'px"></div>' +
        '  <div class="trend-date">' + escapeHtml(d.date) + '</div>' +
        '</div>');
    }).join('');
    container.innerHTML = '<div class="trend-chart">' + cols + '</div>';
  }

  /** 最常查看题目 Top10 表格 */
  function renderTopViewed(rows) {
    const tbody = document.getElementById('topViewedBody');
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="loading-block">暂无查看记录</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(function (r, i) {
      const rankBadge = i < 3
        ? '<span class="badge bg-warning text-dark">' + (i + 1) + '</span>'
        : '<span class="badge bg-light text-secondary">' + (i + 1) + '</span>';
      return (
        '<tr>' +
        '  <td>' + rankBadge + '</td>' +
        '  <td class="fw-semibold">#' + Number(r.id) + '</td>' +
        '  <td>' + escapeHtml(r.subject) + '</td>' +
        '  <td class="text-muted">' + (r.source ? escapeHtml(r.source) : '—') + '</td>' +
        '  <td class="text-end fw-semibold text-primary">' + Number(r.count) + '</td>' +
        '</tr>');
    }).join('');
  }

  /** 最近新增题目列表(LaTeX 内容 MathJax 渲染) */
  function renderRecent(questions) {
    const container = document.getElementById('recentQuestions');
    if (!container) return;
    if (!questions.length) {
      container.innerHTML = '<div class="loading-block">暂无题目</div>';
      return;
    }
    container.innerHTML = questions.map(function (q) {
      const latexHtml = q.question_latex
        ? '<div class="latex-content">' + escapeHtml(q.question_latex) + '</div>'
        : (q.question_image_url
            ? '<div class="text-muted small mt-1"><i class="fa-regular fa-image me-1"></i>图片题目</div>'
            : '');
      return (
        '<div class="recent-q">' +
        '  <div class="d-flex align-items-center flex-wrap gap-2">' +
        '    <span class="fw-semibold">#' + Number(q.id) + '</span>' +
        '    <span class="tag-badge">' + escapeHtml(q.subject) + '</span>' +
        '    ' + difficultyBadge(q.difficulty) +
        (q.chapter ? '<span class="recent-meta">' + escapeHtml(q.chapter) + '</span>' : '') +
        '    <span class="recent-meta ms-auto"><i class="fa-regular fa-clock me-1"></i>' +
             escapeHtml(formatDate(q.created_at, true)) + '</span>' +
        '  </div>' +
        (q.source ? '<div class="recent-meta mt-1"><i class="fa-solid fa-location-dot me-1"></i>' + escapeHtml(q.source) + '</div>' : '') +
        (q.tags && q.tags.length ? '<div class="mt-1">' + tagBadges(q.tags) + '</div>' : '') +
        latexHtml +
        '</div>');
    }).join('');
    // 动态插入的 LaTeX 内容必须重排 MathJax
    typesetMath(container);
  }

  // ============ 用户管理 ============
  function initUserManage() {
    const card = document.getElementById('userManageCard');
    if (!card) return;
    const tbody = document.getElementById('userTableBody');
    const createModal = new bootstrap.Modal(document.getElementById('createUserModal'));
    const pwModal = new bootstrap.Modal(document.getElementById('initialPwModal'));

    async function loadUsers() {
      try {
        const resp = await apiFetch('/api/overview/users');
        const users = resp.data.users;
        tbody.innerHTML = users.map((u) => `
          <tr>
            <td>${u.id}</td>
            <td>${escapeHtml(u.username)}${u.must_change_password ? ' <span class="badge bg-warning text-dark">待改密</span>' : ''}</td>
            <td>${u.role === 'admin' ? '<span class="badge bg-warning text-dark">管理员</span>' : '学生'}</td>
            <td>${u.is_active ? '<span class="badge bg-success">正常</span>' : '<span class="badge bg-secondary">已停用</span>'}</td>
            <td>${escapeHtml(u.created_at || '')}</td>
            <td class="text-end">
              <button class="btn btn-sm btn-outline-secondary me-1" data-action="reset" data-id="${u.id}" data-name="${escapeHtml(u.username)}">重置密码</button>
              <button class="btn btn-sm ${u.is_active ? 'btn-outline-danger' : 'btn-outline-success'}" data-action="toggle" data-id="${u.id}" data-name="${escapeHtml(u.username)}">${u.is_active ? '停用' : '启用'}</button>
            </td>
          </tr>`).join('');
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-3">${escapeHtml(err.message)}</td></tr>`;
      }
    }

    function showInitialPassword(pw) {
      document.getElementById('initialPwValue').value = pw;
      pwModal.show();
    }

    document.getElementById('btnCreateUser').addEventListener('click', () => {
      document.getElementById('newUsername').value = '';
      document.getElementById('newUserRole').value = 'student';
      createModal.show();
    });

    document.getElementById('btnSubmitCreateUser').addEventListener('click', async () => {
      const username = document.getElementById('newUsername').value.trim();
      const role = document.getElementById('newUserRole').value;
      if (!username) { showToast('请输入用户名', 'warning'); return; }
      try {
        const resp = await apiFetch('/api/overview/users', { method: 'POST', body: { username, role } });
        createModal.hide();
        showToast(resp.message || '创建成功', 'success');
        showInitialPassword(resp.data.initial_password);
        loadUsers();
      } catch (err) {
        showToast(err.message, 'danger');
      }
    });

    document.getElementById('btnCopyInitialPw').addEventListener('click', () => {
      const input = document.getElementById('initialPwValue');
      input.select();
      navigator.clipboard.writeText(input.value).then(
        () => showToast('已复制到剪贴板', 'success'),
        () => showToast('复制失败,请手动选择复制', 'warning'));
    });

    tbody.addEventListener('click', async (e) => {
      const btn = e.target.closest('button[data-action]');
      if (!btn) return;
      const { action, id, name } = btn.dataset;
      try {
        if (action === 'reset') {
          if (!confirm(`确认重置用户「${name}」的密码?`)) return;
          const resp = await apiFetch(`/api/overview/users/${id}/reset_password`, { method: 'POST', body: {} });
          showInitialPassword(resp.data.initial_password);
        } else if (action === 'toggle') {
          const resp = await apiFetch(`/api/overview/users/${id}/toggle_active`, { method: 'POST', body: {} });
          showToast(resp.message, 'success');
        }
        loadUsers();
      } catch (err) {
        showToast(err.message, 'danger');
      }
    });

    loadUsers();
  }
})();
