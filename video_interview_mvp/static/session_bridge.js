(() => {
  // Existing dashboard/report code still checks localStorage for an `auth` value.
  // The server has already authenticated this page, so keep only a harmless
  // sentinel there; actual requests are authenticated by the HttpOnly cookie.
  localStorage.setItem('auth', 'cookie-session');

  window.logout = async function logout() {
    try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (_) {}
    localStorage.removeItem('auth');
    localStorage.removeItem('user');
    location.href = '/login';
  };

  const user = JSON.parse(localStorage.getItem('user') || '{}');

  function addInviteControl() {
    if (user.role !== 'hr' || !location.pathname.startsWith('/dashboard')) return;
    const sidebar = document.querySelector('aside > div:last-child');
    if (!sidebar || document.getElementById('teamInviteBtn')) return;

    const button = document.createElement('button');
    button.id = 'teamInviteBtn';
    button.className = 'w-full text-left mt-2 px-3 py-2 text-sm font-semibold text-indigo-600 hover:bg-indigo-50 rounded-lg';
    button.textContent = '+ Пригласить коллегу';
    button.onclick = async () => {
      const roleRaw = prompt('Кого пригласить? Введите: hr или manager', 'manager');
      if (!roleRaw) return;
      const role = roleRaw.trim().toLowerCase() === 'hr' ? 'hr' : 'hiring_manager';
      try {
        const response = await fetch('/api/auth/invitations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Не удалось создать приглашение');
        try { await navigator.clipboard.writeText(data.invite_url); } catch (_) {}
        alert(`Одноразовая ссылка создана на ${data.expires_in_hours} ч.\n\n${data.invite_url}\n\nСсылка скопирована в буфер обмена.`);
      } catch (error) {
        alert(error.message);
      }
    };
    sidebar.insertBefore(button, sidebar.lastElementChild);
  }

  function formatDuration(ms) {
    if (!ms) return '0 сек';
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return `${seconds} сек`;
    return `${Math.floor(seconds / 60)} мин ${seconds % 60} сек`;
  }

  async function addProctorReport() {
    if (!location.pathname.startsWith('/report/')) return;
    const sessionId = location.pathname.split('/').filter(Boolean).pop();
    try {
      const response = await fetch(`/api/proctoring/${sessionId}/summary`);
      if (!response.ok) return;
      const data = await response.json();

      const section = document.createElement('section');
      section.className = 'card p-6';
      section.innerHTML = `
        <div class="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
          <div>
            <div class="text-xs font-bold text-indigo-600">ПРОКТОРИНГ · БРАУЗЕРНЫЕ СИГНАЛЫ</div>
            <h2 class="font-extrabold text-lg mt-1">Целостность сессии</h2>
            <p class="text-sm text-gray-500 mt-1">Сигналы для ручной проверки. Они не входят в техническую оценку кандидата.</p>
          </div>
          <div class="text-xs text-gray-400">${data.total_events || 0} событий</div>
        </div>
        <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-5">
          <div class="bg-gray-50 rounded-xl p-3"><div class="text-xs text-gray-400">Скрытие вкладки</div><b>${data.tab_switches || 0}</b><div class="text-xs text-gray-400 mt-1">${formatDuration(data.tab_hidden_duration_ms)}</div></div>
          <div class="bg-gray-50 rounded-xl p-3"><div class="text-xs text-gray-400">Потеря фокуса</div><b>${data.window_blurs || 0}</b><div class="text-xs text-gray-400 mt-1">${formatDuration(data.window_blur_duration_ms)}</div></div>
          <div class="bg-gray-50 rounded-xl p-3"><div class="text-xs text-gray-400">Paste / Copy</div><b>${data.clipboard_pastes || 0} / ${data.clipboard_copies || 0}</b></div>
          <div class="bg-gray-50 rounded-xl p-3"><div class="text-xs text-gray-400">Fullscreen / media</div><b>${data.fullscreen_exits || 0} / ${data.media_interruptions || 0}</b></div>
        </div>
        <div class="mt-4 p-3 rounded-xl bg-indigo-50 text-xs text-indigo-800 leading-5">${data.disclaimer || ''}</div>`;

      const answers = document.getElementById('answers')?.closest('section');
      if (answers?.parentNode) answers.parentNode.insertBefore(section, answers);
      else document.getElementById('content')?.appendChild(section);
    } catch (_) {}
  }

  addInviteControl();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', addInviteControl, { once: true });
  }
  // report content is rendered asynchronously; give the existing page time to load.
  setTimeout(addProctorReport, 900);
})();
