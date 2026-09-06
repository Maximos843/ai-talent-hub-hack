(() => {
  if (!location.pathname.startsWith('/report/')) return;
  const sessionId = location.pathname.split('/').filter(Boolean).pop();
  const esc = (v = '') => String(v).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');

  function renderFullVideoStatus(media) {
    const status = document.getElementById('fullMediaStatus');
    const warning = document.getElementById('videoWarning');
    if (!status || !media) return;
    const source = media.duration_source || 'unknown';
    const sourceLabel = source === 'server_probe'
      ? 'длительность подтверждена сервером'
      : source === 'client_reported'
        ? 'длительность получена от браузера'
        : source === 'answer_timeline'
          ? 'длительность восстановлена по таймлайну ответов'
          : 'длительность не подтверждена';
    if (media.playable) {
      status.innerHTML = `<span class="media-chip media-ok">✓ Видео доступно · ${esc(sourceLabel)}</span>`;
      if (warning) warning.classList.add('hidden');
    } else {
      status.innerHTML = '<span class="media-chip media-bad">⚠ Техническая проверка файла не завершена</span>';
      if (warning) {
        warning.textContent = 'Запись сохранена, но backend не смог автоматически подтвердить её размер и длительность. Это технический статус файла, а не оценка достоверности кандидата.';
        warning.classList.remove('hidden');
      }
    }
  }

  async function load() {
    try {
      const response = await fetch(`/api/reports/${sessionId}`);
      if (!response.ok) return;
      const data = await response.json();
      renderFullVideoStatus(data.full_video_media);
      const final = data.final_evaluation;
      if (!final) return;

      const strengthEl = document.getElementById('strengths');
      if (strengthEl) strengthEl.innerHTML = final.strengths?.length
        ? final.strengths.map(x => `<li class="p-3 bg-green-50 rounded-xl"><b class="text-sm">${esc(x.point)}</b><div class="text-xs text-gray-500 mt-2">«${esc(x.quote)}» · вопрос ${esc(x.question_id)}</div></li>`).join('')
        : '<li class="text-gray-400">Нет подтверждённых сильных сторон</li>';

      const issuesEl = document.getElementById('weaknesses');
      if (issuesEl) issuesEl.innerHTML = final.issues?.length
        ? final.issues.map(x => `<li class="p-3 bg-amber-50 rounded-xl"><div class="text-xs font-bold text-amber-700">${esc(x.type)}</div><div class="text-sm mt-1">${esc(x.point)}</div>${x.quote ? `<div class="text-xs text-gray-500 mt-2">«${esc(x.quote)}»${x.question_id ? ` · вопрос ${esc(x.question_id)}` : ''}</div>` : ''}</li>`).join('')
        : '<li class="text-gray-400">Явных рисков по ответам не зафиксировано</li>';

      const skillsEl = document.getElementById('skills');
      if (skillsEl) skillsEl.innerHTML = final.competencies?.length
        ? final.competencies.map(x => `<span class="tag" title="${esc((x.evidence_quotes || []).join(' · '))}">${esc(x.name)} · ${esc(x.status)} · ${Number(x.avg_score_0_10 || 0).toFixed(1)}</span>`).join('')
        : '<span class="text-sm text-gray-400">Компетенции не подтверждены данными</span>';

      const areasEl = document.getElementById('areas');
      if (areasEl) areasEl.innerHTML = final.uncovered_vacancy_topics?.length
        ? final.uncovered_vacancy_topics.map(x => `<li class="flex gap-2"><span class="text-indigo-500">•</span><span>${esc(x)}</span></li>`).join('')
        : '<li class="text-gray-400">Нет данных</li>';

      const risksEl = document.getElementById('risks');
      if (risksEl) risksEl.innerHTML = `<li><b>Уверенность итоговой оценки:</b> ${Math.round(Number(final.confidence_0_1 || 0) * 100)}%</li>`;

      const answersSection = document.getElementById('answers')?.closest('section');
      if (!answersSection || document.getElementById('vacancyCoverage')) return;
      const coverage = final.vacancy_coverage || { must_have: [], nice_to_have: [] };
      const statusClass = status => status === 'подтверждено' ? 'text-green-700' : status === 'есть риск' ? 'text-red-700' : 'text-amber-700';
      const rows = items => (items || []).map(x => `<div class="border rounded-xl p-3"><div class="flex justify-between gap-3"><b class="text-sm">${esc(x.topic)}</b><span class="text-xs font-bold ${statusClass(x.status)}">${esc(x.status)}</span></div>${x.evidence_quotes?.length ? `<div class="text-xs text-gray-500 mt-2">«${esc(x.evidence_quotes.join('» · «'))}»</div>` : ''}</div>`).join('') || '<div class="text-sm text-gray-400">Нет данных</div>';
      const section = document.createElement('section');
      section.id = 'vacancyCoverage';
      section.className = 'card p-6';
      section.innerHTML = `<div><h2 class="font-extrabold text-lg">Покрытие требований вакансии</h2><p class="text-sm text-gray-500 mt-1">«Не проверено» не означает отсутствие навыка.</p></div><div class="grid lg:grid-cols-2 gap-6 mt-5"><div><div class="text-xs font-bold text-indigo-600 mb-3">MUST HAVE</div><div class="space-y-2">${rows(coverage.must_have)}</div></div><div><div class="text-xs font-bold text-indigo-600 mb-3">NICE TO HAVE</div><div class="space-y-2">${rows(coverage.nice_to_have)}</div></div></div>`;
      answersSection.parentNode.insertBefore(section, answersSection);
    } catch (_) {}
  }

  setTimeout(load, 500);
})();
