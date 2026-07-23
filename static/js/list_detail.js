/**
 * 题单详情:有序题目(每题链接到 /questions/<id>)+ 顶部进度。
 * owner/admin 额外可加题(按 ID)与移除题目。
 * 依赖 utils.js(apiFetch/escapeHtml/typesetMath)、toast.js(showToast)。
 */
(function () {
  'use strict';

  const app = document.getElementById('listDetailApp');
  if (!app) return;

  const lid = parseInt(app.dataset.lid, 10);
  const currentUserId = parseInt(app.dataset.userId, 10);
  const isAdmin = app.dataset.isAdmin === 'true';

  const ldTitle = document.getElementById('ldTitle');
  const ldDesc = document.getElementById('ldDesc');
  const ldProgressLine = document.getElementById('ldProgressLine');
  const ldBar = document.getElementById('ldBar');
  const ldItems = document.getElementById('ldItems');
  const ldAdd = document.getElementById('ldAdd');

  let editable = false;

  function pct(n, total) {
    if (!total) return 0;
    return Math.max(0, Math.min(100, (n / total) * 100));
  }

  function itemHtml(q, idx) {
    const latex = q.question_latex || '(无题面)';
    const rm = editable
      ? `<button type="button" class="ld-rm" data-qid="${q.id}" title="移除"><i class="fa-solid fa-xmark"></i></button>`
      : '';
    return `
      <div class="ld-item" data-qid="${q.id}">
        <div class="ld-idx">${idx + 1}</div>
        <div class="ld-body">
          <a href="/questions/${q.id}">${escapeHtml(q.subject || '题目')} · #${q.id}</a>
          <div class="ld-latex">${escapeHtml(latex)}</div>
          <div class="ld-meta">${escapeHtml(q.source || '')} ${q.difficulty ? '· ' + escapeHtml(q.difficulty) : ''}</div>
        </div>
        ${rm}
      </div>`;
  }

  function renderProgress(p) {
    const total = p.total || 0;
    ldProgressLine.textContent = `已掌握 ${p.mastered}/${total} · 已做 ${p.done}/${total}`;
    ldBar.innerHTML =
      `<span class="seg-mastered" style="width:${pct(p.mastered, total)}%"></span>` +
      `<span class="seg-done" style="width:${pct(p.done - p.mastered, total)}%"></span>`;
  }

  function render(data) {
    const lst = data.list;
    editable = isAdmin || lst.owner_id === currentUserId;

    ldTitle.innerHTML = escapeHtml(lst.title) +
      (lst.is_official ? '<span class="ld-badge-official">官方</span>' : '');
    ldDesc.textContent = lst.description || '';
    renderProgress(data.progress);

    if (ldAdd) ldAdd.hidden = !editable;

    const questions = data.questions || [];
    if (!questions.length) {
      ldItems.innerHTML = '<p class="ld-empty">这个题单还没有题目。' +
        (editable ? '用上方输入框按题目 ID 加题。' : '') + '</p>';
      return;
    }
    ldItems.innerHTML = questions.map((q, i) => itemHtml(q, i)).join('');
  }

  async function load() {
    try {
      const resp = await apiFetch('/api/lists/' + lid);
      render(resp.data);
    } catch (e) {
      ldTitle.textContent = '加载失败';
      ldItems.innerHTML = '<p class="ld-empty">' + escapeHtml(e.message) + '</p>';
    }
  }

  // 移除题目(事件委托)
  ldItems.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('.ld-rm');
    if (!btn) return;
    const qid = parseInt(btn.dataset.qid, 10);
    try {
      await apiFetch(`/api/lists/${lid}/items/${qid}`, { method: 'DELETE' });
      showToast('已移除', 'success');
      load();
    } catch (e) {
      showToast('移除失败:' + e.message, 'danger');
    }
  });

  // 加题(按 ID)
  const ldAddBtn = document.getElementById('ldAddBtn');
  const ldAddInput = document.getElementById('ldAddInput');
  if (ldAddBtn && ldAddInput) {
    ldAddBtn.addEventListener('click', async () => {
      const qid = parseInt(ldAddInput.value, 10);
      if (!qid || qid < 1) {
        showToast('请输入有效的题目 ID', 'warning');
        return;
      }
      try {
        await apiFetch(`/api/lists/${lid}/items`, {
          method: 'POST', body: { question_id: qid },
        });
        ldAddInput.value = '';
        showToast('已加入', 'success');
        load();
      } catch (e) {
        showToast('加题失败:' + e.message, 'danger');
      }
    });
  }

  load();
})();
