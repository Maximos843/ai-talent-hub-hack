(() => {
  if (!location.pathname.startsWith('/dashboard')) return;
  const root = document.getElementById('view-questions');
  if (!root) return;

  let items = [];
  let editingId = null;

  const esc = (v = '') => String(v).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  const splitLines = value => String(value || '').split(/\n|,/).map(x => x.trim()).filter(Boolean);
  const toastMsg = (message, error = false) => {
    if (typeof window.toast === 'function') return window.toast(message, error);
    alert(message);
  };

  root.innerHTML = `
    <div class="card p-5">
      <div class="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
        <div><h2 class="font-bold">Банк технических вопросов</h2><p class="text-sm text-gray-500 mt-1">Группировка по компетенциям, поиск по тексту и тегам. Изменения используются при подборе вопросов для новых вакансий.</p></div>
        <button id="qbAdd" class="px-4 py-2.5 bg-indigo-600 text-white rounded-xl text-sm font-bold">+ Добавить вопрос</button>
      </div>
      <div class="grid md:grid-cols-[1fr_220px_220px] gap-3 mt-5">
        <input id="qbSearch" class="px-4 py-3 border rounded-xl" placeholder="Поиск по вопросу, критериям или тегам">
        <select id="qbTag" class="px-4 py-3 border rounded-xl bg-white"><option value="">Все теги</option></select>
        <select id="qbCompetency" class="px-4 py-3 border rounded-xl bg-white"><option value="">Все темы</option></select>
      </div>
    </div>
    <div id="qbStats" class="text-xs text-gray-400"></div>
    <div id="questionBank" class="space-y-6"></div>`;

  const modal = document.createElement('div');
  modal.id = 'qbModal';
  modal.className = 'modal fixed inset-0 hidden items-center justify-center z-[95] p-4';
  modal.innerHTML = `
    <div class="bg-white rounded-3xl w-full max-w-3xl max-h-[94vh] overflow-y-auto soft">
      <div class="p-6 border-b flex justify-between"><div><div class="text-xs font-bold text-indigo-600">БАНК ВОПРОСОВ</div><h3 id="qbModalTitle" class="text-xl font-extrabold mt-1"></h3></div><button id="qbClose" class="text-2xl text-gray-400">×</button></div>
      <div class="p-6 space-y-4">
        <div><label class="text-sm font-semibold">Вопрос</label><textarea id="qbQuestion" rows="3" class="w-full mt-2 px-4 py-3 border rounded-xl"></textarea></div>
        <div class="grid md:grid-cols-2 gap-4"><div><label class="text-sm font-semibold">Тема / competency</label><input id="qbEditCompetency" class="w-full mt-2 px-4 py-3 border rounded-xl" placeholder="backend"></div><div><label class="text-sm font-semibold">Теги</label><input id="qbTags" class="w-full mt-2 px-4 py-3 border rounded-xl" placeholder="python, api, backend"></div></div>
        <div><label class="text-sm font-semibold">Референсный ответ</label><textarea id="qbReference" rows="4" class="w-full mt-2 px-4 py-3 border rounded-xl"></textarea></div>
        <div class="grid md:grid-cols-3 gap-4"><div><label class="text-sm font-semibold">Must have</label><textarea id="qbMust" rows="6" class="w-full mt-2 px-3 py-3 border rounded-xl" placeholder="По одному пункту на строку"></textarea></div><div><label class="text-sm font-semibold">Nice to have</label><textarea id="qbNice" rows="6" class="w-full mt-2 px-3 py-3 border rounded-xl"></textarea></div><div><label class="text-sm font-semibold">Red flags</label><textarea id="qbRed" rows="6" class="w-full mt-2 px-3 py-3 border rounded-xl"></textarea></div></div>
      </div>
      <div class="p-6 border-t flex justify-end gap-3"><button id="qbCancel" class="px-4 py-2.5">Отмена</button><button id="qbSave" class="px-5 py-2.5 bg-indigo-600 text-white rounded-xl font-bold">Сохранить</button></div>
    </div>`;
  document.body.appendChild(modal);

  async function request(url, options = {}) {
    const response = await fetch(url, options);
    let data = null;
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
    return data;
  }

  function renderFilters() {
    const tags = [...new Set(items.flatMap(x => x.tags || []))].sort();
    const comps = [...new Set(items.map(x => x.competency || 'general'))].sort();
    const tag = document.getElementById('qbTag'), comp = document.getElementById('qbCompetency');
    const oldTag = tag.value, oldComp = comp.value;
    tag.innerHTML = '<option value="">Все теги</option>' + tags.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
    comp.innerHTML = '<option value="">Все темы</option>' + comps.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
    tag.value = oldTag; comp.value = oldComp;
  }

  function render() {
    const search = document.getElementById('qbSearch').value.trim().toLowerCase();
    const tag = document.getElementById('qbTag').value;
    const competency = document.getElementById('qbCompetency').value;
    const filtered = items.filter(item => {
      const haystack = [item.question, item.competency, ...(item.tags || []), item.reference_answer, ...(item.must_have || [])].join(' ').toLowerCase();
      return (!search || haystack.includes(search)) && (!tag || (item.tags || []).includes(tag)) && (!competency || item.competency === competency);
    });
    const groups = new Map();
    filtered.forEach(item => {
      const key = item.competency || 'general';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    document.getElementById('qbStats').textContent = `${filtered.length} из ${items.length} вопросов · ${groups.size} тем`;
    document.getElementById('questionBank').innerHTML = [...groups.entries()].map(([name, questions]) => `
      <section><div class="flex items-center gap-3 mb-3"><h3 class="font-extrabold text-lg">${esc(name)}</h3><span class="text-xs text-gray-400">${questions.length}</span></div>
      <div class="grid lg:grid-cols-2 gap-4">${questions.map(item => `
        <div class="card p-5"><div class="flex justify-between gap-3"><div class="flex flex-wrap gap-1">${(item.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div><span class="text-xs text-gray-400 whitespace-nowrap">${item.usage_count || 0} использ.</span></div>
        <div class="font-semibold mt-3 leading-6">${esc(item.question)}</div>
        <details class="mt-3"><summary class="text-xs font-semibold text-gray-500 cursor-pointer">Критерии и референс</summary><div class="mt-3 text-xs text-gray-600 space-y-3"><div><b>Must have:</b><ul class="list-disc pl-5 mt-1">${(item.must_have || []).map(x => `<li>${esc(x)}</li>`).join('') || '<li>—</li>'}</ul></div><div><b>Nice to have:</b><ul class="list-disc pl-5 mt-1">${(item.nice_to_have || []).map(x => `<li>${esc(x)}</li>`).join('') || '<li>—</li>'}</ul></div><div><b>Red flags:</b><ul class="list-disc pl-5 mt-1">${(item.red_flags || []).map(x => `<li>${esc(x)}</li>`).join('') || '<li>—</li>'}</ul></div><div><b>Reference:</b><div class="mt-1 leading-5">${esc(item.reference_answer || '—')}</div></div></div></details>
        <button data-edit="${item.database_id}" class="qb-edit mt-4 px-3 py-2 bg-gray-100 rounded-lg text-xs font-bold">Редактировать</button></div>`).join('')}</div></section>`).join('') || '<div class="card p-10 text-center text-gray-400">Ничего не найдено</div>';
    document.querySelectorAll('.qb-edit').forEach(button => button.onclick = () => openEdit(Number(button.dataset.edit)));
  }

  function openEdit(id = null) {
    editingId = id;
    const item = id ? items.find(x => x.database_id === id) : null;
    document.getElementById('qbModalTitle').textContent = item ? 'Редактировать вопрос' : 'Новый вопрос';
    document.getElementById('qbQuestion').value = item?.question || '';
    document.getElementById('qbEditCompetency').value = item?.competency || 'general';
    document.getElementById('qbTags').value = (item?.tags || []).join(', ');
    document.getElementById('qbReference').value = item?.reference_answer || '';
    document.getElementById('qbMust').value = (item?.must_have || []).join('\n');
    document.getElementById('qbNice').value = (item?.nice_to_have || []).join('\n');
    document.getElementById('qbRed').value = (item?.red_flags || []).join('\n');
    modal.classList.remove('hidden'); modal.classList.add('flex');
  }

  function close() { modal.classList.add('hidden'); modal.classList.remove('flex'); }

  async function save() {
    const payload = {
      question: document.getElementById('qbQuestion').value.trim(),
      competency: document.getElementById('qbEditCompetency').value.trim() || 'general',
      tags: splitLines(document.getElementById('qbTags').value),
      reference_answer: document.getElementById('qbReference').value.trim(),
      must_have: splitLines(document.getElementById('qbMust').value),
      nice_to_have: splitLines(document.getElementById('qbNice').value),
      red_flags: splitLines(document.getElementById('qbRed').value)
    };
    if (!payload.question) return toastMsg('Введите текст вопроса', true);
    const button = document.getElementById('qbSave'); button.disabled = true;
    try {
      await request(editingId ? `/api/questions/${editingId}` : '/api/questions', {
        method: editingId ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      close(); await refresh(); toastMsg('Банк вопросов сохранён');
    } catch (error) { toastMsg(error.message, true); }
    finally { button.disabled = false; }
  }

  async function refresh() {
    try { items = await request('/api/questions'); renderFilters(); render(); }
    catch (error) { toastMsg(error.message, true); }
  }

  document.getElementById('qbSearch').addEventListener('input', render);
  document.getElementById('qbTag').addEventListener('change', render);
  document.getElementById('qbCompetency').addEventListener('change', render);
  document.getElementById('qbAdd').onclick = () => openEdit();
  document.getElementById('qbClose').onclick = close;
  document.getElementById('qbCancel').onclick = close;
  document.getElementById('qbSave').onclick = save;
  modal.addEventListener('click', event => { if (event.target === modal) close(); });
  refresh();
})();
