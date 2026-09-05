(() => {
  // Existing dashboard/report templates still read these harmless UI hints.
  // Authentication itself is exclusively the HttpOnly server-side cookie.
  localStorage.setItem('auth', 'cookie-session');

  window.logout = async function logout() {
    try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (_) {}
    localStorage.removeItem('auth');
    localStorage.removeItem('user');
    location.href = '/login';
  };

  const user = JSON.parse(localStorage.getItem('user') || '{}');

  async function createInvite(role, status) {
    status.textContent = 'Создаём ссылку…';
    try {
      const response = await fetch('/api/auth/invitations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Не удалось создать приглашение');
      const input = document.getElementById('teamInviteUrl');
      input.value = data.invite_url;
      document.getElementById('teamInviteResult').classList.remove('hidden');
      status.textContent = `Ссылка действует ${data.expires_in_hours} часов и используется один раз.`;
    } catch (error) {
      status.textContent = error.message;
    }
  }

  function addInviteControl() {
    if (user.role !== 'hr' || !location.pathname.startsWith('/dashboard')) return;
    const sidebar = document.querySelector('aside > div:last-child');
    if (!sidebar || document.getElementById('teamInviteBtn')) return;

    const button = document.createElement('button');
    button.id = 'teamInviteBtn';
    button.className = 'w-full text-left mt-2 px-3 py-2 text-sm font-semibold text-indigo-600 hover:bg-indigo-50 rounded-lg';
    button.textContent = '+ Пригласить коллегу';
    sidebar.insertBefore(button, sidebar.lastElementChild);

    const modal = document.createElement('div');
    modal.id = 'teamInviteModal';
    modal.className = 'fixed inset-0 hidden items-center justify-center z-[90] p-4';
    modal.style.background = 'rgba(20,20,31,.52)';
    modal.innerHTML = `
      <div class="bg-white rounded-3xl w-full max-w-lg p-6 shadow-2xl">
        <div class="flex justify-between gap-3">
          <div><div class="text-xs font-bold text-indigo-600">ДОСТУП В WORKSPACE</div><h3 class="text-xl font-extrabold mt-1">Пригласить коллегу</h3><p class="text-sm text-gray-500 mt-2">Выберите роль. Коллега откроет одноразовую ссылку и сам задаст логин и пароль.</p></div>
          <button id="teamInviteClose" class="text-2xl text-gray-400">×</button>
        </div>
        <div class="grid grid-cols-2 gap-3 mt-5">
          <button data-role="hr" class="invite-role border rounded-2xl p-4 text-left hover:border-indigo-300"><b class="text-sm">HR / рекрутер</b><div class="text-xs text-gray-400 mt-1">Вакансии, кандидаты, первый review</div></button>
          <button data-role="hiring_manager" class="invite-role border rounded-2xl p-4 text-left hover:border-indigo-300"><b class="text-sm">Нанимающий менеджер</b><div class="text-xs text-gray-400 mt-1">Только финальный review после HR</div></button>
        </div>
        <div id="teamInviteResult" class="hidden mt-5 p-4 bg-green-50 rounded-2xl"><div class="text-xs font-bold text-green-800">ССЫЛКА ГОТОВА</div><div class="flex gap-2 mt-2"><input id="teamInviteUrl" readonly class="flex-1 min-w-0 px-3 py-2 border rounded-lg text-xs bg-white"><button id="teamInviteCopy" class="px-3 py-2 bg-white border rounded-lg text-xs font-bold">Копировать</button></div></div>
        <div id="teamInviteStatus" class="text-xs text-gray-400 mt-4">Никаких общих master keys — каждая ссылка отдельная.</div>
      </div>`;
    document.body.appendChild(modal);

    const close = () => { modal.classList.add('hidden'); modal.classList.remove('flex'); };
    button.onclick = () => { document.getElementById('teamInviteResult').classList.add('hidden'); document.getElementById('teamInviteStatus').textContent = 'Никаких общих master keys — каждая ссылка отдельная.'; modal.classList.remove('hidden'); modal.classList.add('flex'); };
    document.getElementById('teamInviteClose').onclick = close;
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    modal.querySelectorAll('.invite-role').forEach(x => x.onclick = () => createInvite(x.dataset.role, document.getElementById('teamInviteStatus')));
    document.getElementById('teamInviteCopy').onclick = async () => {
      const input = document.getElementById('teamInviteUrl');
      try { await navigator.clipboard.writeText(input.value); } catch (_) { input.select(); document.execCommand('copy'); }
      document.getElementById('teamInviteStatus').textContent = 'Ссылка скопирована.';
    };
  }

  function formatDuration(ms) {
    if (!ms) return '0 сек';
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return `${seconds} сек`;
    return `${Math.floor(seconds / 60)} мин ${seconds % 60} сек`;
  }

  function metric(label, value, subtitle = '') {
    return `<div class="bg-gray-50 rounded-xl p-3"><div class="text-xs text-gray-400">${label}</div><b>${value}</b>${subtitle ? `<div class="text-xs text-gray-400 mt-1">${subtitle}</div>` : ''}</div>`;
  }

  async function addProctorReport() {
    if (!location.pathname.startsWith('/report/')) return;
    const sessionId = location.pathname.split('/').filter(Boolean).pop();
    try {
      const response = await fetch(`/api/proctoring/${sessionId}/summary`);
      if (!response.ok) return;
      const data = await response.json();

      const visionState = data.vision_available
        ? '<span class="text-green-700 font-bold">MediaPipe активен</span>'
        : '<span class="text-amber-700 font-bold">MediaPipe не подтвердился</span>';
      const section = document.createElement('section');
      section.className = 'card p-6';
      section.innerHTML = `
        <div class="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
          <div>
            <div class="text-xs font-bold text-indigo-600">ПРОКТОРИНГ · BROWSER + MEDIAPIPE</div>
            <h2 class="font-extrabold text-lg mt-1">Целостность сессии</h2>
            <p class="text-sm text-gray-500 mt-1">${visionState}. Кадры и landmarks не сохраняются; в отчёт попадают только агрегированные события.</p>
          </div>
          <div class="text-xs text-gray-400">${data.total_events || 0} событий</div>
        </div>
        <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-5">
          ${metric('Скрытие вкладки', data.tab_switches || 0, formatDuration(data.tab_hidden_duration_ms))}
          ${metric('Потеря фокуса', data.window_blurs || 0, formatDuration(data.window_blur_duration_ms))}
          ${metric('Paste / Copy', `${data.clipboard_pastes || 0} / ${data.clipboard_copies || 0}`)}
          ${metric('Fullscreen / media', `${data.fullscreen_exits || 0} / ${data.media_interruptions || 0}`)}
        </div>
        <div class="mt-5"><div class="text-xs font-bold text-gray-500 mb-3">FACE SIGNALS</div><div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          ${metric('Лицо отсутствовало', data.face_missing_episodes || 0, formatDuration(data.face_missing_duration_ms))}
          ${metric('Несколько лиц', data.multiple_faces_episodes || 0, formatDuration(data.multiple_faces_duration_ms))}
          ${metric('Поворот головы', data.head_away_episodes || 0, formatDuration(data.head_away_duration_ms))}
          ${metric('Взгляд в сторону', data.gaze_away_episodes || 0, formatDuration(data.gaze_away_duration_ms))}
        </div></div>
        <div class="mt-4 p-3 rounded-xl bg-indigo-50 text-xs text-indigo-800 leading-5">${data.disclaimer || ''}</div>`;

      const answers = document.getElementById('answers')?.closest('section');
      if (answers?.parentNode) answers.parentNode.insertBefore(section, answers);
      else document.getElementById('content')?.appendChild(section);
    } catch (_) {}
  }

  function loadQuestionBankUi() {
    if (user.role !== 'hr' || !location.pathname.startsWith('/dashboard') || document.querySelector('script[data-question-bank-ui]')) return;
    const script = document.createElement('script');
    script.src = '/static/question_bank_ui.js';
    script.dataset.questionBankUi = '1';
    document.body.appendChild(script);
  }

  addInviteControl();
  loadQuestionBankUi();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { addInviteControl(); loadQuestionBankUi(); }, { once: true });
  setTimeout(addProctorReport, 900);
})();
