(() => {
  const pages = [
    ['01-LoginPage.html', '登录'],
    ['02-RegisterPage.html', '注册'],
    ['03-WelcomeModal.html', '欢迎'],
    ['04-ApiKeyModal.html', 'API Key'],
    ['05-EmptyState.html', '空状态'],
    ['06-MainWorkspace.html', '工作区'],
    ['07-ChatPanel.html', '对话'],
    ['08-SettingsDrawer.html', '设置'],
  ];

  const currentFile = decodeURIComponent(location.pathname.split('/').pop());
  const currentIndex = Math.max(0, pages.findIndex(([file]) => file === currentFile));
  const style = document.createElement('style');
  style.textContent = `
    .prototype-nav {
      position: fixed; right: 18px; bottom: 18px; z-index: 9999;
      display: flex; align-items: center; gap: 6px; padding: 6px;
      border: 1px solid rgba(148,163,184,.35); border-radius: 14px;
      background: rgba(255,255,255,.94); box-shadow: 0 12px 32px rgba(15,23,42,.14);
      backdrop-filter: blur(12px); font: 12px/1 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;
    }
    .prototype-nav a, .prototype-nav select {
      height: 32px; border: 0; border-radius: 9px; color: #334155; background: transparent;
    }
    .prototype-nav a {
      width: 32px; display: grid; place-items: center; text-decoration: none;
      font-size: 18px; transition: background .16s, color .16s;
    }
    .prototype-nav a:hover { color: #1e3a8a; background: #eff6ff; }
    .prototype-nav a[aria-disabled="true"] { opacity: .28; pointer-events: none; }
    .prototype-nav select { min-width: 116px; padding: 0 28px 0 10px; cursor: pointer; outline: none; }
    .prototype-nav select:hover { background: #f8fafc; }
    .prototype-toast {
      position: fixed; left: 50%; bottom: 24px; z-index: 10000;
      transform: translate(-50%, 12px); opacity: 0; pointer-events: none;
      padding: 10px 14px; border-radius: 10px; color: white; background: #0f172a;
      box-shadow: 0 10px 28px rgba(15,23,42,.22);
      font: 13px/1.35 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;
      transition: opacity .18s, transform .18s;
    }
    .prototype-toast.is-visible { opacity: 1; transform: translate(-50%, 0); }
  `;
  document.head.appendChild(style);

  const nav = document.createElement('nav');
  nav.className = 'prototype-nav';
  nav.setAttribute('aria-label', '原型页面导航');
  const prev = currentIndex > 0 ? pages[currentIndex - 1][0] : '#';
  const next = currentIndex < pages.length - 1 ? pages[currentIndex + 1][0] : '#';
  nav.innerHTML = `
    <a href="${prev}" aria-label="上一页" aria-disabled="${currentIndex === 0}">‹</a>
    <select aria-label="切换原型页面">
      ${pages.map(([file, label], index) =>
        `<option value="${file}" ${index === currentIndex ? 'selected' : ''}>${String(index + 1).padStart(2, '0')} · ${label}</option>`
      ).join('')}
    </select>
    <a href="${next}" aria-label="下一页" aria-disabled="${currentIndex === pages.length - 1}">›</a>
  `;
  nav.querySelector('select').addEventListener('change', (event) => {
    location.href = event.target.value;
  });
  document.body.appendChild(nav);

  const toast = document.createElement('div');
  toast.className = 'prototype-toast';
  document.body.appendChild(toast);
  let toastTimer;
  window.prototypeToast = (message) => {
    toast.textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 1800);
  };

  document.addEventListener('keydown', (event) => {
    if (!event.altKey) return;
    if (event.key === 'ArrowLeft' && currentIndex > 0) location.href = prev;
    if (event.key === 'ArrowRight' && currentIndex < pages.length - 1) location.href = next;
  });
})();
