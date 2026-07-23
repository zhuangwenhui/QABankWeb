/**
 * 题单广场:官方精选区 + 我的题单区。
 * 依赖 utils.js(apiFetch/escapeHtml)、toast.js(showToast)、Bootstrap Modal。
 */
(function () {
  'use strict';

  const app = document.getElementById('listsApp');
  if (!app) return;

  const currentUserId = parseInt(app.dataset.userId, 10);
  const isAdmin = app.dataset.isAdmin === 'true';

  const officialGrid = document.getElementById('officialGrid');
  const officialEmpty = document.getElementById('officialEmpty');
  const mineGrid = document.getElementById('mineGrid');
  const mineEmpty = document.getElementById('mineEmpty');

  function pct(n, total) {
    if (!total) return 0;
    return Math.max(0, Math.min(100, (n / total) * 100));
  }

  function cardHtml(lst) {
    const p = lst.progress || { total: 0, done: 0, mastered: 0 };
    const total = p.total || 0;
    const masteredPct = pct(p.mastered, total);
    const donePct = pct(p.done - p.mastered, total);
    const official = lst.is_official
      ? '<span class="badge-official">官方</span>' : '';
    return `
      <a class="list-card" href="/lists/${lst.id}">
        <div class="lc-title">${escapeHtml(lst.title)} ${official}</div>
        <div class="lc-desc">${escapeHtml(lst.description || '')}</div>
        <div class="lc-meta">
          <span><i class="fa-solid fa-list-ol me-1"></i>${total} 题</span>
          <span>已掌握 ${p.mastered}/${total}</span>
        </div>
        <div class="lc-bar">
          <span class="seg-mastered" style="width:${masteredPct}%"></span>
          <span class="seg-done" style="width:${donePct}%"></span>
        </div>
      </a>`;
  }

  function render(lists) {
    const official = lists.filter((l) => l.is_official);
    const mine = lists.filter((l) => !l.is_official && l.owner_id === currentUserId);

    officialGrid.innerHTML = official.map(cardHtml).join('');
    officialEmpty.hidden = official.length > 0;
    mineGrid.innerHTML = mine.map(cardHtml).join('');
    mineEmpty.hidden = mine.length > 0;
  }

  async function load() {
    try {
      const resp = await apiFetch('/api/lists');
      render(resp.data.lists || []);
    } catch (e) {
      officialGrid.innerHTML = '';
      officialEmpty.hidden = false;
      officialEmpty.textContent = '加载失败:' + e.message;
    }
  }

  // ------------------------------------------------------------ 新建题单
  const createModalEl = document.getElementById('createModal');
  const createModal = createModalEl ? new bootstrap.Modal(createModalEl) : null;
  const officialCheckWrap = document.getElementById('officialCheckWrap');
  if (isAdmin && officialCheckWrap) officialCheckWrap.hidden = false;

  const btnCreate = document.getElementById('btnCreateList');
  if (btnCreate && createModal) {
    btnCreate.addEventListener('click', () => {
      document.getElementById('newListTitle').value = '';
      document.getElementById('newListDesc').value = '';
      const off = document.getElementById('newListOfficial');
      if (off) off.checked = false;
      createModal.show();
    });
  }

  const btnSubmit = document.getElementById('btnCreateSubmit');
  if (btnSubmit) {
    btnSubmit.addEventListener('click', async () => {
      const title = document.getElementById('newListTitle').value.trim();
      const description = document.getElementById('newListDesc').value.trim();
      const off = document.getElementById('newListOfficial');
      if (!title) {
        showToast('请填写标题', 'warning');
        return;
      }
      const body = { title, description };
      if (isAdmin && off && off.checked) body.is_official = true;
      try {
        const resp = await apiFetch('/api/lists', { method: 'POST', body });
        if (createModal) createModal.hide();
        showToast('题单已创建', 'success');
        window.location.href = '/lists/' + resp.data.id;
      } catch (e) {
        showToast('创建失败:' + e.message, 'danger');
      }
    });
  }

  load();
})();
