/**
 * 导航「复习」链接的待复习红点徽标。
 * 数据源:GET /api/review/stats 的 due_today。仅在登录态(导航渲染出 #reviewBadge)时运行。
 */
(function () {
  'use strict';
  var badge = document.getElementById('reviewBadge');
  if (!badge || typeof apiFetch !== 'function') return;

  apiFetch('/api/review/stats').then(function (resp) {
    var n = (resp.data && resp.data.due_today) || 0;
    if (n > 0) {
      badge.textContent = n > 99 ? '99+' : String(n);
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  }).catch(function () { /* 静默:徽标缺失不影响主流程 */ });
})();
