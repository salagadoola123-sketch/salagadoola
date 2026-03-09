/**
 * VIBE 가사지 content.js v15.2
 * 핵심: 새 곡 감지 후 500ms 대기 → playTime 읽어서 시작점 확정
 *       이후 rAF로 playTime 계속 추적 (칼싱크)
 */

const WS_URL = 'ws://localhost:6789';
let ws = null, wsReady = false;
let currentTrackId = 0, lastSentId = 0;

let G_lyrics   = [];
let G_trackKey = '';
let G_pos      = 0;
let G_lastIdx  = -1;
let G_timer    = null;
let G_lastWall = null;
let G_isPlaying = true;

// ── VIBE playTime ──
function getVibePos() {
  const t = parseFloat(document.body.getAttribute('data-vibe-time'));
  return (isNaN(t) || t <= 0) ? -1 : t;
}

// ── 가사 표시 ──
function showLyric(idx) {
  const safeIdx = Math.max(0, Math.min(idx < 0 ? 0 : idx, G_lyrics.length - 1));
  // G_lastIdx 캐시 제거 - 항상 업데이트
  G_lastIdx = safeIdx;

  const cur  = document.getElementById('gasaji-cur');
  const prev = document.getElementById('gasaji-prev');
  const next = document.getElementById('gasaji-next');
  if (!cur) return;

  const ct = G_lyrics[safeIdx]?.text?.trim()     ?? '';
  const pt = G_lyrics[safeIdx-1]?.text?.trim()   ?? '';
  const nt = G_lyrics[safeIdx+1]?.text?.trim()   ?? '';

  cur.textContent  = ct;
  prev.textContent = pt;
  next.textContent = nt;
  cur.style.display  = ct ? 'block' : 'none';
  prev.style.display = pt ? 'block' : 'none';
  next.style.display = nt ? 'block' : 'none';
}

function findIdx(pos) {
  let idx = -1;
  for (let i = 0; i < G_lyrics.length; i++) {
    if (G_lyrics[i].time <= pos) idx = i; else break;
  }
  return idx;
}

// ── rAF 타이머 ──
function startTimer() {
  if (G_timer) return;
  G_lastWall = performance.now();
  function raf() {
    const now     = performance.now();
    const vibePos = getVibePos();
    if (vibePos >= 0) {
      G_pos = vibePos; // 칼싱크
    } else if (G_isPlaying) {
      G_pos += (now - G_lastWall) / 1000;
    }
    G_lastWall = now;
    if (G_lyrics.length) showLyric(findIdx(G_pos));
    G_timer = requestAnimationFrame(raf);
  }
  G_timer = requestAnimationFrame(raf);
}

function stopTimer() {
  if (G_timer) { cancelAnimationFrame(G_timer); G_timer = null; }
}

function clearAll() {
  stopTimer();
  G_lyrics = []; G_trackKey = '';
  G_pos = 0; G_lastIdx = -1;
  ['gasaji-cur','gasaji-prev','gasaji-next'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.style.display = 'none'; }
  });
}

// ── 새 곡 시작: 500ms 후 playTime 읽어서 시작점 확정 ──
let _startTimer = null;
function startNewTrack(lyr) {
  stopTimer();
  if (_startTimer) { clearTimeout(_startTimer); _startTimer = null; }

  G_trackKey = lyr[0].text + '|' + lyr.length;
  G_lyrics   = lyr;
  G_lastIdx  = -1;
  G_pos      = 0;

  // 즉시 첫 가사 표시
  showLyric(0);

  // 500ms 후 playTime으로 시작점 보정
  _startTimer = setTimeout(() => {
    const vibePos = getVibePos();
    if (vibePos > 0) {
      G_pos = vibePos;
      G_lastIdx = -1;
      console.log('[가사지] 🎯 시작점 확정: ' + vibePos.toFixed(1) + 's');
    } else {
      console.log('[가사지] ⚠️ playTime 없음, 0부터 시작');
    }
    startTimer();
  }, 500);
}

// ── 일시정지 감지 ──
let _lastPlayState = null;
setInterval(() => {
  const playing = !!document.querySelector(
    '[aria-label*="일시정지"],[aria-label*="Pause"],[aria-label*="pause"]'
  );
  if (playing === _lastPlayState) return;
  _lastPlayState = playing;
  G_isPlaying    = playing;
  if (playing && !G_timer && G_lyrics.length) startTimer();
}, 200);

// ── 위젯 주입 ──
function injectWidget() {
  if (document.getElementById('gasaji-widget')) return;
  const style = document.createElement('style');
  style.textContent = `
    @font-face { font-family:'NanumOgBiCe'; src:local('Nanum OgBiCe'),local('NanumOgBiCe'); }
    #gasaji-widget {
      position:fixed!important; bottom:100px!important; left:50%!important;
      transform:translateX(-50%)!important; z-index:2147483647!important;
      width:90%; max-width:800px;
      pointer-events:none; user-select:none;
      font-family:'NanumOgBiCe','Noto Sans KR',sans-serif;
    }
    #gasaji-inner { display:flex; flex-direction:column; align-items:center; gap:8px; min-height:80px; }
    #gasaji-prev, #gasaji-next {
      font-size:18px; color:rgba(0,0,0,0.75); font-weight:400;
      text-align:center; max-width:700px;
      white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
      background:rgba(255,255,255,0.45);
      padding:10px 24px; border-radius:14px;
      border:1px solid rgba(255,255,255,0.3);
      box-shadow:0 2px 10px rgba(0,0,0,0.15);
    }
    #gasaji-cur {
      font-size:28px; font-weight:800; color:#000;
      text-align:center; max-width:780px;
      white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
      background:rgba(255,255,255,0.92);
      padding:14px 32px; border-radius:16px;
      border:1px solid rgba(255,255,255,0.5);
      box-shadow:0 6px 20px rgba(0,0,0,0.2);
    }
    #gasaji-handle {
      position:absolute; top:-28px; left:50%; transform:translateX(-50%);
      width:56px; height:20px; background:rgba(255,255,255,0.08);
      border:1px solid rgba(255,255,255,0.15); border-radius:10px;
      cursor:grab; pointer-events:all;
      display:flex; align-items:center; justify-content:center; gap:3px;
      opacity:0; transition:opacity 0.2s;
    }
    #gasaji-widget:hover #gasaji-handle { opacity:0.6; }
    .gd { width:3px; height:3px; border-radius:50%; background:rgba(255,255,255,0.6); }
    #gasaji-badge {
      position:absolute; top:-24px; right:0; font-size:9px; font-family:monospace;
      color:rgba(255,255,255,0.3); pointer-events:none;
    }
  `;
  document.head.appendChild(style);
  const w = document.createElement('div');
  w.id = 'gasaji-widget';
  w.innerHTML = `
    <div style="position:relative">
      <div id="gasaji-handle"><div class="gd"></div><div class="gd"></div><div class="gd"></div></div>
      <div id="gasaji-badge">● 연결 중...</div>
      <div id="gasaji-inner">
        <div id="gasaji-prev"></div>
        <div id="gasaji-cur"></div>
        <div id="gasaji-next"></div>
      </div>
    </div>`;
  document.body.appendChild(w);
  const h = document.getElementById('gasaji-handle');
  let drag=false,sx,sy,ol,ob;
  h.addEventListener('mousedown',e=>{
    drag=true; w.style.pointerEvents='all';
    const r=w.getBoundingClientRect();
    sx=e.clientX; sy=e.clientY; ol=r.left+r.width/2; ob=window.innerHeight-r.bottom;
    e.preventDefault();
  });
  document.addEventListener('mousemove',e=>{
    if(!drag)return;
    w.style.left=(ol+e.clientX-sx)+'px';
    w.style.bottom=(ob-(e.clientY-sy))+'px';
    w.style.transform='none';
  });
  document.addEventListener('mouseup',()=>{drag=false;w.style.pointerEvents='none';});
}

function badge(t,c){const b=document.getElementById('gasaji-badge');if(b){b.textContent=t;b.style.color=c;}}
function send(d){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify(d));}

// ── WebSocket ──
function connectWS() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    wsReady = true;
    badge('● LIVE','rgba(168,255,120,0.9)');
    if (currentTrackId>0 && currentTrackId!==lastSentId) setTimeout(sendId,300);
  };
  ws.onmessage = e => {
    let msg; try{msg=JSON.parse(e.data);}catch{return;}
    if (msg.type==='track_change'){G_trackKey='';return;} // 가사 유지, key만 초기화
    const lyr=msg.lyrics;
    if (!Array.isArray(lyr)||lyr.length===0){clearAll();return;}
    const key=lyr[0].text+'|'+lyr.length;
    if (key!==G_trackKey) {
      startNewTrack(lyr);
      console.log('[가사지] 🎵 새곡 '+lyr.length+'줄');
    } else {
      if (!G_timer) startTimer();
    }
  };
  ws.onclose = ()=>{
    wsReady=false; stopTimer();
    badge('● 재연결...','rgba(255,80,80,0.8)');
    setTimeout(connectWS,2000);
  };
  ws.onerror = ()=>{wsReady=false;};
}

// ── trackId 감지 ──
function extractId(url){const m=url.match(/\/track\/(\d{5,})\/info/);return m?parseInt(m[1]):0;}

function sendId(){
  if(!wsReady||!currentTrackId||currentTrackId===lastSentId)return;
  lastSentId=currentTrackId;
  send({type:'trackid_found',track_id:currentTrackId,
        track:{title:'',artist:'',track_id:currentTrackId,position:0,is_playing:true},
        cookies:document.cookie});
  console.log('[가사지] ✅ trackId→'+currentTrackId);
}

const _origFetch=window.fetch;
window.fetch=async function(...args){
  const res=await _origFetch.apply(this,args);
  const url=args[0] instanceof Request?args[0].url:String(args[0]);
  const id=extractId(url);
  if(id>0&&id!==currentTrackId){currentTrackId=id;lastSentId=0;if(wsReady)sendId();}
  return res;
};

new PerformanceObserver(list=>{
  for(const e of list.getEntries()){
    const id=extractId(e.name);
    if(id>0&&id!==currentTrackId){currentTrackId=id;lastSentId=0;if(wsReady)sendId();}
  }
}).observe({entryTypes:['resource']});

function initTrackId(){
  const entries=performance.getEntriesByType('resource');
  for(let i=entries.length-1;i>=Math.max(0,entries.length-100);i--){
    const id=extractId(entries[i].name);
    if(id>0){currentTrackId=id;sendId();return;}
  }
}
setTimeout(initTrackId,500);
setTimeout(initTrackId,2000);
setTimeout(initTrackId,5000);

setInterval(()=>{
  if(!wsReady)return;
  send({type:'position_update',track:{title:'',artist:'',track_id:currentTrackId,position:G_pos,is_playing:G_isPlaying}});
},1000);

chrome.runtime.onMessage.addListener((msg,_,res)=>{
  if(msg.type==='get_status'){res({connected:wsReady,lyrics:G_lyrics.length,pos:G_pos,wp:getVibePos()});return true;}
});

injectWidget();
connectWS();
console.log('[가사지 v15.2] 로드됨');