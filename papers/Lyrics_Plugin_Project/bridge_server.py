"""
🎵 VIBE → OBS 가사 브릿지 서버 v9
- trackid_found 시 항상 VIBE API 호출 (캐시 무효화)
- SMTC + LRCLIB fallback
"""

import asyncio
import json
import re
import threading
import requests
import logging
import subprocess
import base64
from dataclasses import dataclass, asdict
from typing import Optional, List

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

WS_HOST = "localhost"
WS_PORT = 6789
POLL_INTERVAL = 1.0

@dataclass
class TrackInfo:
    title:      str   = ""
    artist:     str   = ""
    album:      str   = ""
    position:   float = 0.0
    duration:   float = 0.0
    is_playing: bool  = False
    thumbnail:  str   = ""
    track_id:   int   = 0

@dataclass
class LyricLine:
    time: float
    text: str

# ════════════════════════════════════════════════
# 1. SMTC
# ════════════════════════════════════════════════

class SMTCReader:
    def __init__(self):
        self._available = False
        self._try_init()

    def _try_init(self):
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager
            )
            self._Manager = Manager
            self._available = True
            log.info("✅ SMTC (Windows Media Session) 초기화 성공")
        except ImportError:
            log.warning("⚠️  winsdk 없음 → 창 타이틀 폴백 모드 사용")
        except Exception as e:
            log.warning(f"⚠️  SMTC 초기화 오류: {e}")

    async def get_current_track(self) -> Optional[TrackInfo]:
        if not self._available:
            return None
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager
            )
            from winsdk.windows.media import MediaPlaybackStatus
            manager  = await Manager.request_async()
            session  = manager.get_current_session()
            if not session:
                return None
            media_props = await session.try_get_media_properties_async()
            timeline    = session.get_timeline_properties()
            playback    = session.get_playback_info()
            position = timeline.position.total_seconds() if timeline.position else 0
            duration = timeline.end_time.total_seconds() if timeline.end_time else 0
            thumb_url = ""
            if media_props.thumbnail:
                try:
                    stream = await media_props.thumbnail.open_read_async()
                    data   = await stream.read_bytes_async(stream.size)
                    thumb_url = "data:image/jpeg;base64," + base64.b64encode(bytes(data)).decode()
                except Exception:
                    pass
            is_playing = playback.playback_status == MediaPlaybackStatus.PLAYING
            return TrackInfo(
                title=media_props.title or "",
                artist=media_props.artist or "",
                album=media_props.album_title or "",
                position=position,
                duration=duration,
                is_playing=is_playing,
                thumbnail=thumb_url,
                track_id=0
            )
        except Exception as e:
            log.debug(f"SMTC read error: {e}")
            return None

# ════════════════════════════════════════════════
# 2. 창 타이틀 폴백
# ════════════════════════════════════════════════

class WindowTitleReader:
    PATTERNS = [
        r'^(.+?)\s*-\s*(.+?)\s*[-|]\s*VIBE',
        r'^(.+?)\s*[-–]\s*(.+?)\s*[-|]\s*Spotify',
        r'^(.+?)\s*[-–]\s*(.+?)\s*[-|]\s*YouTube',
        r'^(.+?)\s*[-–]\s*(.+)$',
    ]

    def get_current_track(self) -> Optional[TrackInfo]:
        try:
            cmd = (
                "Get-Process | Where-Object {"
                "$_.MainWindowTitle -ne '' -and "
                "$_.ProcessName -notin @('chrome','msedge','brave','firefox') -and "
                "$_.ProcessName -in @('VIBE','Spotify','YouTubeMusic','flo','genie')"
                "} | Select-Object ProcessName,MainWindowTitle | ConvertTo-Json"
            )
            result = subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            windows = json.loads(result.stdout or "[]")
            if isinstance(windows, dict):
                windows = [windows]
            if not windows:
                return None
            windows.sort(key=lambda w: w.get('ProcessName','') == 'VIBE', reverse=True)
            for win in windows:
                title = win.get('MainWindowTitle','')
                for pattern in self.PATTERNS:
                    m = re.match(pattern, title, re.IGNORECASE)
                    if m:
                        return TrackInfo(
                            artist=m.group(1).strip(),
                            title=m.group(2).strip(),
                            is_playing=True,
                            track_id=0
                        )
        except Exception as e:
            log.debug(f"Window title read error: {e}")
        return None

# ════════════════════════════════════════════════
# 3. 가사 API
# ════════════════════════════════════════════════

class LyricsProvider:
    def __init__(self):
        self._cache = {}
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer":    "https://vibe.naver.com/",
            "Origin":     "https://vibe.naver.com",
            "Accept":     "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def get_lyrics(self, artist: str, title: str) -> list:
        key = (artist.lower(), title.lower())
        if key in self._cache:
            return self._cache[key]
        lines = self._fetch_lrclib(artist, title) or []
        self._cache[key] = lines
        return lines

    def get_lyrics_by_vibe_trackid(self, track_id: int, cookies: str = "") -> list:
        try:
            url = f"https://apis.naver.com/vibeWeb/musicapiweb/track/{track_id}/info"
            headers = dict(self._session.headers)
            if cookies:
                headers["Cookie"] = cookies
            r = requests.get(url, headers=headers, timeout=6)
            log.info(f"  VIBE API 응답: {r.status_code}, {len(r.content)}bytes (trackId: {track_id})")
            if r.status_code != 200 or not r.content:
                return []
            try:
                data = r.json()
            except json.JSONDecodeError:
                log.warning(f"VIBE API JSON 파싱 실패 (trackId: {track_id})")
                return []
            lines = self._parse_vibe_lyric_json(data)
            if lines:
                cache_key = f"vibe_{track_id}"
                self._cache[cache_key] = lines
                log.info(f"✅ VIBE 가사 로드 성공: {len(lines)}줄 (trackId: {track_id})")
            else:
                log.warning(f"VIBE 가사 파싱 실패 (trackId: {track_id})")
            return lines
        except Exception as e:
            log.error(f"Vibe lyric API 오류: {e} (trackId: {track_id})")
            return []

    def _parse_vibe_lyric_json(self, data: dict) -> list:
        try:
            lyric_obj = (
                data.get("response",{}).get("result",{}).get("trackInformation",{}) or
                data.get("response",{}).get("result",{}).get("lyric",{})
            )
            if not lyric_obj:
                return []
            # 형식 1: syncLyric 문자열
            sync_str = lyric_obj.get("syncLyric")
            if sync_str and isinstance(sync_str, str) and '|' in sync_str:
                lines = []
                for block in sync_str.split('#'):
                    if '|' in block:
                        time_str, text = block.split('|', 1)
                        try:
                            lines.append(LyricLine(time=float(time_str.strip()), text=text.strip()))
                        except ValueError:
                            continue
                if lines:
                    return lines
            # 형식 2: syncLyric dict
            sync_dict = lyric_obj.get("syncLyric")
            if sync_dict and isinstance(sync_dict, dict) and sync_dict.get("contents"):
                starts = sync_dict.get("startTimeIndex", [])
                texts  = sync_dict["contents"][0].get("text", [])
                lines  = []
                for i, text in enumerate(texts):
                    if i < len(starts):
                        lines.append(LyricLine(time=float(starts[i]), text=text.strip()))
                if lines:
                    return lines
            # 형식 3: 일반 가사
            plain = lyric_obj.get("lyric") or lyric_obj.get("normalLyric",{}).get("text","")
            if plain:
                raw = [l.strip() for l in plain.split('\n') if l.strip()]
                if raw:
                    return [LyricLine(time=i*4.0, text=line) for i, line in enumerate(raw)]
        except Exception as e:
            log.debug(f"VIBE JSON 파싱 오류: {e}")
        return []

    def _fetch_lrclib(self, artist: str, title: str) -> Optional[list]:
        try:
            r = requests.get(
                "https://lrclib.net/api/get",
                params={"artist_name": artist, "track_name": title},
                timeout=5
            )
            if r.status_code == 200:
                data = r.json()
                lrc_text = data.get("syncedLyrics") or data.get("plainLyrics","")
                if lrc_text:
                    lines = self._parse_lrc(lrc_text)
                    if lines:
                        log.info(f"✅ LRCLIB 가사 {len(lines)}줄: {artist} - {title}")
                        return lines
        except Exception as e:
            log.debug(f"LRCLIB error: {e}")
        return None

    def _parse_lrc(self, lrc_text: str) -> list:
        lines   = []
        pattern = re.compile(r'\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.+)')
        for line in lrc_text.split('\n'):
            m = pattern.match(line.strip())
            if m:
                t    = int(m.group(1))*60 + int(m.group(2)) + int((m.group(3) or '0').ljust(3,'0'))/1000
                text = m.group(4).strip()
                if text:
                    lines.append(LyricLine(time=t, text=text))
        return sorted(lines, key=lambda x: x.time)

# ════════════════════════════════════════════════
# 4. WebSocket 서버
# ════════════════════════════════════════════════

class BridgeServer:
    def __init__(self):
        self.smtc            = SMTCReader()
        self.wintitle        = WindowTitleReader()
        self.lyrics_provider = LyricsProvider()
        self.clients         = set()
        self._last_track_key = ""
        self._current_lyrics = []
        self._current_track  = TrackInfo()
        self._event_flag     = None

    async def handler(self, websocket):
        self.clients.add(websocket)
        log.info(f"🔌 클라이언트 연결됨: {websocket.remote_address}")
        try:
            await self._send_state(websocket)
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_client_message(data)
                except Exception as e:
                    log.debug(f"메시지 처리 오류: {e}")
        except Exception as e:
            log.debug(f"WS 통신 오류: {e}")
        finally:
            self.clients.discard(websocket)
            log.info("🔌 클라이언트 연결 종료")

    async def _handle_client_message(self, data: dict):
        msg_type   = data.get("type","")
        track_data = data.get("track",{})

        # ── trackid_found ──
        if msg_type == "trackid_found":
            vibe_track_id = data.get("track_id")
            if not vibe_track_id:
                return
            log.info(f"📥 content.js로부터 VIBE trackId 수신: {vibe_track_id}")

            # track_id 업데이트
            self._current_track.track_id = vibe_track_id

            # 항상 캐시 무효화 후 VIBE API 새로 호출
            cache_key = f"vibe_{vibe_track_id}"
            self.lyrics_provider._cache.pop(cache_key, None)

            cookies = data.get("cookies","")
            self._current_lyrics = await asyncio.get_event_loop().run_in_executor(
                None, self.lyrics_provider.get_lyrics_by_vibe_trackid, vibe_track_id, cookies
            )
            await self._broadcast({
                "type":   "update",
                "track":  asdict(self._current_track),
                "lyrics": [{"time": l.time, "text": l.text} for l in self._current_lyrics],
            })
            return

        # ── position_update ──
        if msg_type == "position_update":
            if track_data:
                self._current_track.position   = track_data.get("position",   self._current_track.position)
                self._current_track.is_playing = track_data.get("is_playing", self._current_track.is_playing)
                if track_data.get("track_id"):
                    self._current_track.track_id = track_data["track_id"]
            await self._broadcast({
                "type":   "update",
                "track":  asdict(self._current_track),
                "lyrics": [{"time": l.time, "text": l.text} for l in self._current_lyrics],
            })
            return

        # ── track_change ──
        if msg_type == "track_change":
            self._current_lyrics = []
            await self._broadcast({"type":"track_change","track":track_data,"lyrics":[]})
            return

    async def _send_state(self, ws):
        try:
            await ws.send(json.dumps({
                "track":  asdict(self._current_track),
                "lyrics": [{"time": l.time, "text": l.text} for l in self._current_lyrics],
            }, ensure_ascii=False))
        except:
            pass

    async def _broadcast(self, data: dict):
        if not self.clients:
            return
        msg = json.dumps(data, ensure_ascii=False)
        await asyncio.gather(*[c.send(msg) for c in list(self.clients)], return_exceptions=True)

    # ── 폴링 루프 ──
    async def poll_loop(self):
        log.info(f"🎵 미디어 폴링 시작 (간격: {POLL_INTERVAL}s)")
        self._event_flag = asyncio.Event()
        loop = asyncio.get_event_loop()

        def on_smtc_event(reason):
            loop.call_soon_threadsafe(self._event_flag.set)

        await self._attach_smtc_events(on_smtc_event)

        while True:
            track = await self._read_track()

            if track and self._is_browser_title(track):
                track = None

            if track:
                if self._current_track.track_id and \
                   track.title == self._current_track.title and \
                   track.artist == self._current_track.artist:
                    track.track_id = self._current_track.track_id

                track_key = f"{track.artist}||{track.title}"

                if track_key != self._last_track_key and track.title:
                    self._last_track_key = track_key
                    log.info(f"🎶 새 곡 감지: {track.artist} - {track.title}")
                    self._current_lyrics = []
                    await self._broadcast({"type":"track_change","track":asdict(track),"lyrics":[]})

                    if not track.track_id:
                        log.info(f"   🔍 LRCLIB 검색: {track.artist} - {track.title}")
                        self._current_lyrics = await asyncio.get_event_loop().run_in_executor(
                            None, self.lyrics_provider.get_lyrics, track.artist, track.title
                        )
                        if self._current_lyrics:
                            log.info(f"   ✅ LRCLIB {len(self._current_lyrics)}줄")
                        else:
                            log.warning(f"   ⚠️  LRCLIB 가사 없음 - trackId 대기 중...")
                    else:
                        log.info(f"   ⏳ VIBE trackId 대기 중...")

                # 현재 트랙 정보 업데이트
                self._current_track.title      = track.title
                self._current_track.artist     = track.artist
                self._current_track.album      = track.album
                self._current_track.position   = track.position
                self._current_track.duration   = track.duration
                self._current_track.is_playing = track.is_playing
                self._current_track.thumbnail  = track.thumbnail

                await self._broadcast({
                    "type":   "update",
                    "track":  asdict(self._current_track),
                    "lyrics": [{"time": l.time, "text": l.text} for l in self._current_lyrics],
                })
            else:
                if self._last_track_key:
                    self._last_track_key = ""
                    log.info("⏹ 재생 중지됨")
                    await self._broadcast({"type":"stopped"})

            try:
                await asyncio.wait_for(self._event_flag.wait(), timeout=POLL_INTERVAL)
                self._event_flag.clear()
            except asyncio.TimeoutError:
                pass

    async def _attach_smtc_events(self, callback):
        if not self.smtc._available:
            return
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager
            )
            manager = await Manager.request_async()
            manager.add_current_session_changed(lambda m, _: callback("session_changed"))
            session = manager.get_current_session()
            if session:
                session.add_media_properties_changed(lambda s, _: callback("media_changed"))
                session.add_playback_info_changed(lambda s, _: callback("playback_changed"))
                log.info("✅ SMTC 이벤트 리스너 등록 완료")
                log.info("   → 다음 곡 넘어가면 즉시 자동 감지됩니다")
        except Exception as e:
            log.debug(f"SMTC event attach error: {e}")
            log.info("⚠️  SMTC 이벤트 리스너 실패 → 폴링 단독 모드")

    async def _read_track(self) -> Optional[TrackInfo]:
        track = await self.smtc.get_current_track()
        if not track:
            track = self.wintitle.get_current_track()
        return track

    @staticmethod
    def _is_browser_title(track: TrackInfo) -> bool:
        combined = f"{track.title} {track.artist}"
        junk = ["Chrome","Edge","Firefox","Safari","VIBE(바이브)","보관함",
                "플레이리스트","공지사항","네이버","Naver","Claude","실시간 방송",
                "localhost","http://","https://","Google","YouTube","새 탭"]
        for j in junk:
            if j.lower() in combined.lower():
                return True
        if not track.artist.strip() and len(track.title) > 40:
            return True
        if " > " in track.title:
            return True
        return False

    async def start(self):
        import websockets
        log.info(f"🚀 브릿지 서버 시작: ws://{WS_HOST}:{WS_PORT}")
        async with websockets.serve(self.handler, WS_HOST, WS_PORT):
            await self.poll_loop()

# ════════════════════════════════════════════════
# 5. HTTP 서버
# ════════════════════════════════════════════════

def start_http_server(port=6790):
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("localhost", port), SimpleHTTPRequestHandler)
    log.info(f"📡 HTTP 서버: http://localhost:{port}/obs_overlay.html")
    server.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()
    bridge = BridgeServer()
    try:
        asyncio.run(bridge.start())
    except KeyboardInterrupt:
        log.info("👋 서버 종료")