import { FaceLandmarker, FilesetResolver } from 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/+esm';

(() => {
  const push = (type, metadata = {}) => {
    if (typeof window.__proctorPush === 'function') window.__proctorPush(type, metadata);
  };

  const SAMPLE_INTERVAL_MS = 250; // ~4 FPS: enough for integrity signals, light on CPU.
  const NO_FACE_GRACE_MS = 1200;
  const MULTI_FACE_GRACE_MS = 900;
  const HEAD_AWAY_GRACE_MS = 1500;
  const GAZE_AWAY_GRACE_MS = 2000;

  let landmarker = null;
  let timer = null;
  let running = false;
  let lastVideoTime = -1;

  const states = {
    noFace: { pendingAt: null, activeAt: null },
    multiFace: { pendingAt: null, activeAt: null },
    headAway: { pendingAt: null, activeAt: null },
    gazeAway: { pendingAt: null, activeAt: null }
  };

  function statusBadge(text, ok = true) {
    let badge = document.getElementById('visionProctorStatus');
    if (!badge) {
      const cam = document.querySelector('.cam');
      if (!cam) return;
      badge = document.createElement('div');
      badge.id = 'visionProctorStatus';
      badge.style.cssText = 'position:absolute;left:12px;top:12px;padding:7px 9px;border-radius:999px;background:rgba(18,19,27,.64);color:#fff;font-size:11px;font-weight:700;z-index:4';
      cam.appendChild(badge);
    }
    badge.textContent = text;
    badge.style.opacity = ok ? '0.95' : '0.72';
  }

  function transition(name, bad, graceMs, startEvent, endEvent, metadata = {}) {
    const state = states[name];
    const now = Date.now();
    if (bad) {
      if (state.activeAt) return;
      if (!state.pendingAt) state.pendingAt = now;
      if (now - state.pendingAt >= graceMs) {
        state.activeAt = state.pendingAt;
        state.pendingAt = null;
        push(startEvent, metadata);
      }
      return;
    }
    state.pendingAt = null;
    if (state.activeAt) {
      const duration = now - state.activeAt;
      state.activeAt = null;
      push(endEvent, { ...metadata, duration_ms: duration });
    }
  }

  function mean(points) {
    if (!points.length) return null;
    return points.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }), { x: 0, y: 0 });
  }

  function irisCenter(lm, indices) {
    const points = indices.map(i => lm[i]).filter(Boolean);
    const m = mean(points);
    if (!m) return null;
    return { x: m.x / points.length, y: m.y / points.length };
  }

  function distance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function headAway(lm) {
    // Nose displacement inside the cheek-to-cheek span is a stable, cheap yaw proxy.
    const left = lm[234], right = lm[454], nose = lm[1];
    if (!left || !right || !nose) return false;
    const width = Math.max(0.001, distance(left, right));
    const midX = (left.x + right.x) / 2;
    const yawProxy = Math.abs(nose.x - midX) / width;

    // Extreme pitch is detected by nose position inside forehead/chin span.
    const forehead = lm[10], chin = lm[152];
    let pitchBad = false;
    if (forehead && chin) {
      const span = Math.max(0.001, Math.abs(chin.y - forehead.y));
      const normalizedY = (nose.y - forehead.y) / span;
      pitchBad = normalizedY < 0.30 || normalizedY > 0.72;
    }
    return yawProxy > 0.16 || pitchBad;
  }

  function gazeAway(lm) {
    if (lm.length < 478) return false;
    const leftIris = irisCenter(lm, [468, 469, 470, 471, 472]);
    const rightIris = irisCenter(lm, [473, 474, 475, 476, 477]);
    const leftA = lm[33], leftB = lm[133], rightA = lm[362], rightB = lm[263];
    if (!leftIris || !rightIris || !leftA || !leftB || !rightA || !rightB) return false;

    function eyeOffset(iris, a, b) {
      const width = Math.max(0.001, distance(a, b));
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      return {
        x: Math.abs(iris.x - mid.x) / width,
        y: Math.abs(iris.y - mid.y) / width
      };
    }
    const l = eyeOffset(leftIris, leftA, leftB);
    const r = eyeOffset(rightIris, rightA, rightB);
    const horizontal = (l.x + r.x) / 2;
    const vertical = (l.y + r.y) / 2;
    return horizontal > 0.18 || vertical > 0.16;
  }

  function closeOpenStates() {
    transition('noFace', false, 0, 'face_missing', 'face_returned');
    transition('multiFace', false, 0, 'multiple_faces', 'single_face_returned');
    transition('headAway', false, 0, 'head_away', 'head_returned');
    transition('gazeAway', false, 0, 'gaze_away', 'gaze_returned');
  }

  async function createLandmarker() {
    const wasmRoot = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm';
    const model = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
    const vision = await FilesetResolver.forVisionTasks(wasmRoot);
    const common = {
      baseOptions: { modelAssetPath: model, delegate: 'GPU' },
      runningMode: 'VIDEO',
      numFaces: 2,
      minFaceDetectionConfidence: 0.55,
      minFacePresenceConfidence: 0.55,
      minTrackingConfidence: 0.50,
      outputFaceBlendshapes: false,
      outputFacialTransformationMatrixes: false
    };
    try {
      landmarker = await FaceLandmarker.createFromOptions(vision, common);
      return 'GPU';
    } catch (_) {
      landmarker = await FaceLandmarker.createFromOptions(vision, {
        ...common,
        baseOptions: { modelAssetPath: model, delegate: 'CPU' }
      });
      return 'CPU';
    }
  }

  async function sample() {
    if (!running || !landmarker) return;
    const video = document.getElementById('video');
    if (!video || video.readyState < 2 || video.paused || !video.srcObject) return;
    if (video.currentTime === lastVideoTime) return;
    lastVideoTime = video.currentTime;

    try {
      const result = landmarker.detectForVideo(video, performance.now());
      const faces = result.faceLandmarks || [];
      const count = faces.length;
      transition('noFace', count === 0, NO_FACE_GRACE_MS, 'face_missing', 'face_returned', { face_count: count });
      transition('multiFace', count > 1, MULTI_FACE_GRACE_MS, 'multiple_faces', 'single_face_returned', { face_count: count });

      if (count === 1) {
        const lm = faces[0];
        const headBad = headAway(lm);
        transition('headAway', headBad, HEAD_AWAY_GRACE_MS, 'head_away', 'head_returned');
        // Iris heuristics become unreliable during large head turns, so do not double-count.
        transition('gazeAway', !headBad && gazeAway(lm), GAZE_AWAY_GRACE_MS, 'gaze_away', 'gaze_returned');
      } else {
        transition('headAway', false, 0, 'head_away', 'head_returned');
        transition('gazeAway', false, 0, 'gaze_away', 'gaze_returned');
      }
    } catch (error) {
      console.warn('MediaPipe sample failed', error);
    }
  }

  async function start() {
    if (running) return;
    running = true;
    statusBadge('Face proctor · загрузка');
    try {
      const delegate = await createLandmarker();
      if (!running) return;
      push('vision_ready', { sample_fps: Math.round(1000 / SAMPLE_INTERVAL_MS), delegate });
      statusBadge(`Face proctor · ${delegate}`);
      timer = setInterval(sample, SAMPLE_INTERVAL_MS);
    } catch (error) {
      console.warn('MediaPipe Face Landmarker unavailable', error);
      push('vision_unavailable', { reason: 'model_init_failed' });
      statusBadge('Face proctor недоступен', false);
      // Browser/tab proctoring remains active; interview must never be blocked by ML.
    }
  }

  function stop() {
    running = false;
    if (timer) clearInterval(timer);
    timer = null;
    closeOpenStates();
    try { landmarker?.close(); } catch (_) {}
    landmarker = null;
  }

  window.addEventListener('talent-interview-started', start);
  window.addEventListener('talent-interview-finished', stop);
  window.addEventListener('pagehide', stop);
})();
