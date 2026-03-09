# 🎵 VIBE → OBS 가사 싱크 브릿지

## 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│  VIBE 크롬 브라우저                                                        │
│  (Windows에서 재생 중)                                           │
└───────────────────┬─────────────────────────────────────────────┘
                    │ Windows SMTC
                    │ (System Media Transport Controls)
                    │ → 곡명 / 아티스트 / 재생위치 / 앨범아트
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  bridge_server.py  (Python 로컬 서버)                            │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │ SMTC Reader  │ →  │ Lyrics API   │ →  │ WebSocket 서버   │   │
│  │ (재생 감지)  │    │ (가사 로드)  │    │ ws://localhost   │   │
│  └──────────────┘    └──────────────┘    │ :6789            │   │
│                       LRCLIB API          └──────────────────┘   │
│                       lyrics.ovh                                  │
└───────────────────────────────────────┬─────────────────────────┘
                                        │ WebSocket
                                        │ (실시간 곡정보 + LRC 가사)
                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  obs_overlay.html  (OBS 브라우저 소스)                           │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  재생 위치 보간 (rAF ticker)                             │    │
│  │  가사 이진탐색 → 현재 줄 하이라이트                      │    │
│  │  방송 화면 오버레이 렌더링                                │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## 설치 방법

### 1. Python 의존성 설치
```bash
pip install websockets winsdk requests
```

### 2. 파일 구성
```
📁 lyrics-bridge/
  ├── bridge_server.py    ← Python 서버
  └── obs_overlay.html    ← OBS 브라우저 소스
```

### 3. 서버 실행
```bash
python bridge_server.py
```
터미널에 다음이 표시되면 성공:
```
[INFO] ✅ SMTC (Windows Media Session) 초기화 성공
[INFO] 🚀 브릿지 서버 시작: ws://localhost:6789
[INFO] 📡 HTTP 서버: http://localhost:6790/obs_overlay.html
```

### 4. OBS 설정
1. OBS → Sources 패널 → `+` 클릭
2. **Browser** (브라우저) 선택
3. URL: `http://localhost:6790/obs_overlay.html`
4. Width: `1920` / Height: `200`
5. ✅ **Shutdown source when not visible** 체크 해제
6. ✅ **Refresh browser when scene becomes active** 체크

### 5. VIBE에서 음악 재생
→ 자동으로 OBS에 가사가 표시됩니다!

---

## 가사 소스 우선순위

| 순위 | 소스 | 타임코드 | 비고 |
|------|------|----------|------|
| 1 | LRCLIB | ✅ LRC 싱크 | 무료, 한국 곡 지원 |
| 2 | lyrics.ovh | ❌ 균등 분배 | 무료, 가사만 |
| 3 | 직접 LRC | ✅ LRC 싱크 | `lyrics/` 폴더에 파일 저장 |

### 로컬 LRC 파일 우선 사용
`lyrics/아티스트 - 곡명.lrc` 파일을 만들면 API 대신 사용됩니다.

---

## 커스터마이징

### OBS 오버레이 스타일 변경
`obs_overlay.html` 상단 CSS 변수 수정:
```css
:root {
  --accent: #a8ff78;    /* 가사 글로우 색상 */
  --accent2: #78ffd6;   /* 진행바 색상 */
  --glow: rgba(168, 255, 120, 0.6);
}
```

### 글꼴 크기 변경
```css
.lyric-current { font-size: 32px; }  /* 현재 가사 크기 */
.lyric-prev    { font-size: 15px; }  /* 이전/다음 가사 */
```

### 위치 변경 (하단 → 중앙 등)
```css
.overlay {
  justify-content: center;  /* flex 위치 조정 */
  padding-bottom: 0;
}
```

---

## 문제 해결

| 문제 | 원인 | 해결 |
|------|------|------|
| SMTC 안 됨 | winsdk 미설치 | `pip install winsdk` |
| 가사 없음 | API 못 찾음 | LRC 파일 직접 추가 |
| OBS 연결 안 됨 | 포트 충돌 | `WS_PORT = 6789` 변경 |
| 한국 곡 가사 없음 | LRCLIB 미지원 | LRCLIB.net에서 기여 가능 |

---

## 향후 확장 아이디어

- **유튜브 연동**: YouTube IFrame API의 `getCurrentTime()` → 같은 구조 재사용
- **카카오 가사 API**: 공식 API 신청 시 한국 곡 지원 강화
- **OBS WebSocket 연동**: obs-websocket 플러그인으로 장면 전환 연동
- **Discord 표시**: Discord Rich Presence로 현재 곡 친구에게 공유
