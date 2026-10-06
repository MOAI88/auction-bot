# 경매 퀀트 텔레그램 봇 (GitHub Actions)

- 매일 08:50(KST) 이후 첫 확인 때: 서울·남양주 다세대·연립 중 퀀트 기준(무대출 15%·월 순현금 20만)에 맞는 **새 물건**만 알림
- 메시지 아래 **[↻ 지금 다시 조사]** 버튼 또는 봇에게 `조사` / `/scan` 입력 → 그 시점 기준 **전체 목록** 다시 발송
- 매시 정각에 리스너가 재시작되어 약 54분 동안 버튼을 기다림 (GitHub 사정으로 시작이 몇 분 늦을 수 있음)

## 설정
1. 이 폴더 내용을 **Public** 저장소에 올림 (`.github/workflows/bot.yml` 포함)
2. Settings → Secrets and variables → Actions → New repository secret
   - `TELEGRAM_BOT_TOKEN` : BotFather 토큰
   - `TELEGRAM_CHAT_ID` : 숫자 채팅 ID
3. Actions 탭 → auction-bot → Run workflow (첫 실행)

기준값(보증금·수리비·목표 수익률 등)은 alert.py 상단 `P = dict(...)` 에서 수정.
