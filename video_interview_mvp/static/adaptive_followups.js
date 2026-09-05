(() => {
  if (!window.__INTERVIEW_TOKEN__ || !location.pathname.startsWith('/interview/')) return;
  if (typeof submitAnswer !== 'function' || typeof showQuestion !== 'function') return;

  const plannedQuestionCount = Array.isArray(questions) ? questions.length : 0;

  function showFollowUp(followUp) {
    if (!followUp?.question || !followUp?.session_question_id) {
      showQuestion(index + 1);
      return;
    }
    // Reuse the existing recording/ASR pipeline by temporarily making the
    // current slot point at the generated InterviewQuestion. The planned index
    // does not advance until probing for this root question is complete.
    questions[index] = {
      session_question_id: followUp.session_question_id,
      question: followUp.question,
      is_follow_up: true,
      follow_up_index: followUp.follow_up_index,
      root_question_id: followUp.root_question_id
    };
    answerId = null;
    resetAnswer();
    const current = Math.max(1, Number(followUp.follow_up_index || 1));
    const max = Math.max(current, Number(followUp.max_follow_ups || 2));
    $('progress').textContent = `Вопрос ${index + 1} из ${plannedQuestionCount} · уточнение ${current}/${max}`;
    $('state').textContent = 'Уточняющий вопрос по предыдущему ответу.';
    ai(followUp.question, `Уточняющий вопрос ${current}/${max}`, true);
  }

  submitAnswer = async function submitAdaptiveAnswer() {
    const text = $('transcript').value.trim();
    if (!text) return toast('Транскрипция пустая', true);
    if (!answerId) return toast('Ответ ещё не сохранён', true);
    $('submit').disabled = true;
    $('state').textContent = 'Анализируем ответ и решаем, нужно ли уточнение…';
    try {
      const response = await fetch('/api/interviews/correct-transcript', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer_id: answerId, corrected_transcript: text })
      });
      if (!response.ok) throw new Error(await errText(response));
      const data = await response.json();
      me(text);
      if (data.follow_up) showFollowUp(data.follow_up);
      else showQuestion(index + 1);
    } catch (error) {
      toast(`Не удалось подтвердить ответ: ${error.message}`, true);
      $('state').textContent = 'Проверьте распознанный текст перед отправкой.';
    } finally {
      $('submit').disabled = false;
    }
  };
})();
