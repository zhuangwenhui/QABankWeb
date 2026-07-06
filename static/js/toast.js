/**
 * 消息提示组件:showToast(message, type)
 * type: success | danger | warning | info
 */
function showToast(message, type = 'success', delay = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) {
    alert(message);
    return;
  }
  const icons = {
    success: 'fa-circle-check',
    danger: 'fa-circle-xmark',
    warning: 'fa-triangle-exclamation',
    info: 'fa-circle-info',
  };
  // Bootstrap 5.1.3 无 text-bg-* 语义类,改用 bg-*;深色底(success/danger)配白字与白色关闭按钮,
  // 浅色底(warning/info)配深字与默认关闭按钮,保证颜色区分与关闭按钮可见。
  const styles = {
    success: { bg: 'bg-success', text: 'text-white', closeWhite: true },
    danger: { bg: 'bg-danger', text: 'text-white', closeWhite: true },
    warning: { bg: 'bg-warning', text: 'text-dark', closeWhite: false },
    info: { bg: 'bg-info', text: 'text-dark', closeWhite: false },
  };
  const s = styles[type] || styles.info;
  const el = document.createElement('div');
  el.className = `toast align-items-center border-0 ${s.bg} ${s.text}`;
  el.setAttribute('role', 'alert');
  el.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">
        <i class="fa-solid ${icons[type] || icons.info} me-2"></i>${escapeHtml(message)}
      </div>
      <button type="button" class="btn-close${s.closeWhite ? ' btn-close-white' : ''} me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  container.appendChild(el);
  const toast = new bootstrap.Toast(el, { delay });
  el.addEventListener('hidden.bs.toast', () => el.remove());
  toast.show();
}
