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

  // MediaPipe module uses the same queue/batching path. It never receives access
  // to auth/session credentials and cannot upload images or landmarks.
  window.__proctorPush = push;

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

  function attachTrackListeners() {
    const video = document.getElementById('video');
    const stream = video?.srcObject;
    if (!stream) return;
    stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => push('camera_ended'), { once: true }));
    stream.getAudioTracks().forEach(track => track.addEventListener('ended', () => push('microphone_ended'), { once: true }));
  }

  function startTracking() {
    if (active) return;
    const interview = document.getElementById('interview');
    const video = document.getElementById('video');
    // Start only after the product flow really entered the interview. A rejected
    // /start request must not create false proctor events or spin up MediaPipe.
    if (!interview || interview.classList.contains('hidden') || !video?.srcObject) return false;

    active = true;
    push(document.fullscreenElement ? 'fullscreen_enter' : 'fullscreen_exit');
    attachTrackListeners();
    flushTimer = setInterval(() => flush(), 5000);
    window.dispatchEvent(new CustomEvent('talent-interview-started'));
    return true;
  }

  function stopTracking() {
    if (!active) return;
    active = false;
    window.dispatchEvent(new CustomEvent('talent-interview-finished'));
    if (flushTimer) clearInterval(flushTimer);
    flushTimer = null;
    flush(true);
  }

  const startButton = document.getElementById('startInterview');
  if (startButton) {
    startButton.addEventListener('click', () => {
      if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen().catch(() => {});
      }
      let attempts = 0;
      const waitForInterview = () => {
        attempts += 1;
        if (startTracking() || attempts >= 12) return;
        setTimeout(waitForInterview, 250);
      };
      setTimeout(waitForInterview, 250);
    }, { capture: true });
  }

  // Stop ML/browser tracking as soon as the existing flow reveals its final page.
  const finalSection = document.getElementById('final');
  if (finalSection && window.MutationObserver) {
    new MutationObserver(() => {
      if (!finalSection.classList.contains('hidden')) stopTracking();
    }).observe(finalSection, { attributes: true, attributeFilter: ['class'] });
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

  window.addEventListener('pagehide', stopTracking);
})();
