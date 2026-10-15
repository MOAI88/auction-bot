# auction-bot 작업 규칙

텔레그램 경매 알림 봇. 로직은 전부 alert.py, 실행은 .github/workflows/bot.yml (매시 리스너 약 54분, 정기 알림 KST 08:50 월세 퀀트 / 13:00 개축 퀀트).

- 수정은 main 에 직접 커밋한다. 봇이 실행할 때마다 main 을 git pull 해서 쓰기 때문에 푸시 즉시 반영된다.
- 커밋 전 `python -m py_compile alert.py` 필수.
- seen.json, state.json, gaechuk.json 은 봇이 수시로 커밋한다. 작업 전에 `git pull --rebase` 하고, 사용자가 요청하지 않는 한 이 세 파일은 건드리지 않는다. 충돌 나면 원격 버전을 유지한다.
- 텔레그램 실제 발송은 사용자가 요청할 때만. 평소 확인은 `--dry` / `--gaechuk-dry` 로 한다.
- 기준값(예산, 평당 단가, 알림 시각 등)은 파일 상단 상수로 두고, 바꾸면 README.md 도 같이 갱신한다.
- 보고는 한국어로 짧게, 표는 쓰지 않는다.
- 비밀값(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)은 repo secrets 에만 둔다. 코드·로그·커밋 메시지에 절대 노출하지 않는다.
- 데이터 출처는 경매마당 /search, /caview 서버 렌더 HTML 만 쓴다 (/api/ 는 robots 금지). 요청 간격 1~2초 유지.
