# 경매 퀀트 텔레그램 봇 (GitHub Actions)

- **오전 08:50(KST) 이후 첫 확인 — 월세 퀀트**: 서울·남양주 다세대·연립 중 퀀트 기준(무대출 15%·월 순현금 20만)에 맞는 **새 물건**만 알림
- **오후 13:00(KST) 이후 첫 확인 — 개축 퀀트**: 서울 단독·다가구·근린주택·근생·숙박·고시원 중 2003년 이전 승인이면서 건축물대장 용적률이 현행 서울시 조례 상한을 넘는 **새 물건**만 알림 (위반건축물·지분·구분건물 제외, 초과 10㎡ 이상)
- 메시지 아래 버튼 2개 → 그 시점 기준 **전체 목록** 다시 발송
  - **[↻ 월세 퀀트]** 또는 `조사` / `/scan`
  - **[🏗 개축 퀀트]** 또는 `개축` / `/gaechuk`
- 매시 정각에 리스너가 재시작되어 약 54분 동안 버튼을 기다림 (GitHub 사정으로 시작이 몇 분 늦을 수 있음)
- 개축 퀀트는 사건 상세(건축물대장·토지대장·지역지구)를 `gaechuk.json`에 30일 캐시

## 설정
1. 이 폴더 내용을 **Public** 저장소에 올림 (`.github/workflows/bot.yml` 포함)
2. Settings → Secrets and variables → Actions → New repository secret
   - `TELEGRAM_BOT_TOKEN` : BotFather 토큰
   - `TELEGRAM_CHAT_ID` : 숫자 채팅 ID
3. Actions 탭 → auction-bot → Run workflow (첫 실행)

기준값(보증금·수리비·목표 수익률 등)은 alert.py 상단 `P = dict(...)` 에서 수정.
개축 퀀트 기준(승인연도·최소 초과면적·알림 시각)은 `G_MAX_YEAR`, `G_MIN_EXCESS`, `G_DAILY_AT` 에서 수정.
