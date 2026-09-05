(() => {
  if (!location.pathname.startsWith('/report/')) return;
  const sessionId = location.pathname.split('/').filter(Boolean).pop();
  const esc = (v = '') => String(v).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');

  async function load() {
    try {
      const response = await fetch(`/api/reports/${sessionId}`);
      if (!response.ok) return;
      const data = await response.json();
      const chains = data.adaptive_follow_ups || [];
      if (!chains.length || document.getElementById('adaptiveFollowUpReport')) return;

      const section = document.createElement('section');
      section.id = 'adaptiveFollowUpReport';
      section.className = 'card p-6';
      section.innerHTML = `
        <div class="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
          <div><div class="text-xs font-bold text-indigo-600">АДАПТИВНОЕ ИНТЕРВЬЮ</div><h2 class="font-extrabold text-lg mt-1">Уточняющие вопросы</h2><p class="text-sm text-gray-500 mt-1">LLM задаёт до двух уточнений по исходному вопросу, если это помогает проверить глубину знаний. Уточнения не получают отдельный дополнительный вес в итоговом score.</p></div>
          <div class="text-xs text-gray-400">${chains.reduce((sum, chain) => sum + Number(chain.follow_up_count || 0), 0)} уточнений</div>
        </div>
        <div class="space-y-5 mt-5">${chains.map(chain => `
          <article class="border rounded-2xl p-5">
            <div class="flex flex-col md:flex-row md:items-start justify-between gap-3"><div><div class="text-xs font-bold text-indigo-600">ИСХОДНЫЙ ВОПРОС · ${esc(chain.competency || 'general')}</div><div class="font-bold mt-1 leading-6">${esc(chain.root_question)}</div></div><div class="bg-gray-50 rounded-xl px-3 py-2 text-sm font-bold whitespace-nowrap">Итог по теме: ${chain.resolved_root_score_0_10 != null ? Number(chain.resolved_root_score_0_10).toFixed(1) + '/10' : '—'}</div></div>
            ${chain.root_transcript ? `<div class="mt-3 p-3 bg-gray-50 rounded-xl text-xs text-gray-600"><b>Основной ответ:</b> ${esc(chain.root_transcript)}</div>` : ''}
            <div class="space-y-3 mt-4">${(chain.follow_ups || []).map(item => `
              <div class="border-l-4 border-indigo-200 pl-4 py-1">
                <div class="flex flex-wrap items-center gap-2"><span class="text-xs font-bold text-indigo-700">Уточнение ${item.index}/2</span><span class="text-xs text-gray-400">${item.source === 'possible_extra_questions' ? 'из подсказок банка' : 'сформулировано LLM'}</span></div>
                <div class="font-semibold text-sm mt-1">${esc(item.question)}</div>
                <div class="grid md:grid-cols-2 gap-2 mt-3"><div class="bg-indigo-50 rounded-xl p-3 text-xs"><b>Зачем спросили</b><div class="mt-1 text-indigo-900">${esc(item.reason || '—')}</div></div><div class="bg-gray-50 rounded-xl p-3 text-xs"><b>Что проверяли</b><div class="mt-1 text-gray-700">${esc(item.focus || '—')}</div></div></div>
                ${item.transcript ? `<div class="mt-3 text-xs text-gray-600"><b>Ответ:</b> ${esc(item.transcript)}</div>` : '<div class="mt-3 text-xs text-gray-400">Ответ не найден.</div>'}
                <div class="text-xs text-gray-400 mt-2">Оценка ответа: ${item.score_0_10 != null ? Number(item.score_0_10).toFixed(1) + '/10' : '—'} · уверенность решения спросить: ${Math.round(Number(item.decision_confidence_0_1 || 0) * 100)}%</div>
              </div>`).join('')}</div>
          </article>`).join('')}</div>`;

      const answers = document.getElementById('answers')?.closest('section');
      if (answers?.parentNode) answers.parentNode.insertBefore(section, answers);
      else document.getElementById('content')?.appendChild(section);
    } catch (_) {}
  }

  setTimeout(load, 650);
})();
