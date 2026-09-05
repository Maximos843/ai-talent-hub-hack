(() => {
  const token = window.__INTERVIEW_TOKEN__;
  if (!token) return;

  let active = false;
  let queue = [];
  let hiddenStartedAt = null;
  let blurStartedAt = null;
  let flushTimer = null;

  const now = () => Date.now();

  function stateMeta(extra = {}) {
    const recordingButton = document.getElementById('record');
    const answerRecording = !!recordingButton && /Завершить ответ/.test(recordingButton.textContent || '');
    const progress = document.getElementById('progress')?.textContent || '';
    const match = progress.match(/Вопрос\s+(\d+)/i);
    return {
      question_index: match ? Math.max(0, Number(match[1]) - 1) : 0,
      answer_recording: answerRecording,
      visibility_state: document.visibilityState,
      ...extra
    };
  }

  function push(type, metadata = {}) {
    if (!active) return;
    queue.push({ type, client_ts_ms: now(), metadata: stateMeta(metadata) });
    if (queue.length >= 8) flush();
  }

  async function flush(useBeacon = false) {
    if (!queue.length) return;
    const batch = queue.splice(0, 30);
    const body = JSON.stringify({ events: batch });
    const url = `/api/interviews/${token}/proctor-events`;
    try {
      if (useBeacon && navigator.sendBeacon) {
        navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }));
        return;
      }
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true
      });
      if (!response.ok && queue.length < 60) queue.unshift(...batch);
    } catch (_) {
      if (queue.length < 60) queue.unshift(...batch);
    }
  }

  function startTracking() {
    if (active) return;
    active = true;
    push('fullscreen_enter', { duration_ms: 0 });
    flushTimer = setInterval(() => flush(), 5000);

    const video = document.getElementById('video');
    const stream = video?.srcObject;
    if (stream) {
      stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => push('camera_ended')));
      stream.getAudioTracks().forEach(track => track.addEventListener('ended', () => push('microphone_ended')));
    }
  }

  const startButton = document.getElementById('startInterview');
  if (startButton) {
    startButton.addEventListener('click', () => {
      // Fullscreen is best-effort: browsers may reject it, and interview must not
      // fail if they do. The user has just clicked the explicit start control.
      if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen().catch(() => {});
      }
      setTimeout(startTracking, 700);
    }, { capture: true });
  }

  document.addEventListener('visibilitychange', () => {
    if (!active) return;
    if (document.hidden) {
      hiddenStartedAt = now();
      push('tab_hidden');
    } else {
      const duration = hiddenStartedAt ? now() - hiddenStartedAt : 0;
      hiddenStartedAt = null;
      push('tab_visible', { duration_ms: duration });
    }
  });

  window.addEventListener('blur', () => {
    if (!active || document.hidden) return;
    blurStartedAt = now();
    push('window_blur');
  });

  window.addEventListener('focus', () => {
    if (!active || document.hidden) return;
    const duration = blurStartedAt ? now() - blurStartedAt : 0;
    blurStartedAt = null;
    push('window_focus', { duration_ms: duration });
  });

  document.addEventListener('copy', () => push('clipboard_copy'));
  document.addEventListener('cut', () => push('clipboard_cut'));
  document.addEventListener('paste', () => push('clipboard_paste'));

  document.addEventListener('fullscreenchange', () => {
    if (!active) return;
    push(document.fullscreenElement ? 'fullscreen_enter' : 'fullscreen_exit');
  });

  window.addEventListener('offline', () => push('network_offline'));
  window.addEventListener('online', () => push('network_online'));

  window.addEventListener('pagehide', () => {
    if (flushTimer) clearInterval(flushTimer);
    flush(true);
  });
})();
