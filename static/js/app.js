/**
 * 应用入口:全局初始化。
 */
document.addEventListener('DOMContentLoaded', () => {
  // flash 消息 4 秒后自动淡出
  document.querySelectorAll('.flash-messages .alert').forEach((el) => {
    setTimeout(() => {
      el.classList.remove('show');
      setTimeout(() => el.remove(), 300);
    }, 4000);
  });
});
