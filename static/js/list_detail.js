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

  /** 算进度条百分比,并夹到 0-100。total 为 0 时回 0 —— 空题单不能除零。 */
  function pct(n, total) {
    if (!total) return 0;
    return Math.max(0, Math.min(100, (n / total) * 100));
  }

  /**
   * 题单里的一行题目。序号用**在题单中的位置**(idx+1)而不是题号 ——
   * 题单是有序的,位置才是它在这份清单里的身份。
   * 移除按钮仅在 editable 时出现(自己的题单或管理员)。
   */
  function itemHtml(q, idx) {
    const latex = (window.QDRender ? window.QDRender.previewSource(q) : q.question_latex) || '(无题面)';
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

  /**
   * 顶部进度条:已掌握 / 已做两段叠加。
   *
   * 第二段宽度用 done - mastered 而不是 done:已掌握的题同时也算已做,
   * 直接用 done 两段会重叠,总宽超过 100%。
   */
  function renderProgress(p) {
    const total = p.total || 0;
    ldProgressLine.textContent = `已掌握 ${p.mastered}/${total} · 已做 ${p.done}/${total}`;
    ldBar.innerHTML =
      `<span class="seg-mastered" style="width:${pct(p.mastered, total)}%"></span>` +
      `<span class="seg-done" style="width:${pct(p.done - p.mastered, total)}%"></span>`;
  }

  /** 渲染整页:标题、编辑权限、进度条、题目列表,最后交给渲染管线排版数学。 */
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
    // 题面预览就地重渲成 markdown(只做 escapeHtml 会显示裸 ## / ** / :::)
    if (window.QDRender) {
      ldItems.querySelectorAll('.ld-latex').forEach((node) => {
        const raw = node.textContent;
        if (raw) { node.classList.add('solbody'); window.QDRender.renderPreviewInto(node, raw, 'zh'); }
      });
      window.QDRender.typeset(ldItems);
    } else {
      typesetMath(ldItems);
    }
  }

  /** 拉取题单详情并渲染。失败时把标题换成「加载失败」,不留空白页。 */
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
