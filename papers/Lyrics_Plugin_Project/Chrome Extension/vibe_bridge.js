// vibe_bridge.js - MAIN world
// playerCore.currentAudio.currentTime 을 DOM에 기록 (곡마다 리셋되는 진짜 재생 위치)
(function() {
  if (window.__vibeBridgeRunning) return;
  window.__vibeBridgeRunning = true;

  function sync() {
    try {
      const t = window.webPlayer?.playerCore?.currentAudio?.currentTime;
      if (typeof t === 'number' && t >= 0) {
        document.body.setAttribute('data-vibe-time', t);
      }
    } catch(e) {}
  }

  function rafLoop() { sync(); requestAnimationFrame(rafLoop); }
  requestAnimationFrame(rafLoop);
  setInterval(sync, 100); // 백업
})();