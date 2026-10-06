"""경매 월세 퀀트 알림 (서울·남양주)
사용: python3 alert.py --test   → 텔레그램 연결 테스트
      python3 alert.py          → 물건 수집 → 퀀트 필터 → 텔레그램 발송
토큰은 같은 폴더 telegram.env 에서만 읽습니다.
"""
import json, os, re, sys, time, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- 퀀트 가정값 (단위: 만원) ----
P = dict(dep=1000, hold=40, law=70, evict=100, fix=500, tax_low=0.011, tax_high=0.084,
         rate=0.055, loan_fee=30, cap_bid=0.80, min_loan_bid=10000, target=0.15, min_cash=20)
# 지역별 방공제 / 규제 LTV
REGION = {
    "서울": dict(bang=5500, ltv=0.0),          # 규제지역: 임대용 대출 사실상 불가
    "남양주_과밀": dict(bang=4800, ltv=0.70),   # 다산·도농·호평·평내·금곡·일패·이패·삼패·가운·수석·지금
    "남양주_기타": dict(bang=2500, ltv=0.70),   # 화도·진접·오남·별내·와부·조안·수동 등
}
NYJ_DENSE = ["다산", "도농", "호평", "평내", "금곡", "일패", "이패", "삼패", "가운", "수석", "지금"]
RENTS = [50, 60, 70]  # 시나리오 월세

def region_of(addr):
    if addr.startswith("서울"): return "서울"
    if "남양주" in addr:
        return "남양주_과밀" if any(k in addr for k in NYJ_DENSE) else "남양주_기타"
    return None

def calc(bid, rent, pub, reg, p=P):
    """bid: 낙찰가, pub: 공시가(모르면 None)"""
    r = REGION[reg]
    tax = p["tax_low"] if (pub is None or pub <= 10000) else p["tax_high"]
    loan = 0.0
    if r["ltv"] > 0 and bid >= p["min_loan_bid"]:
        loan = max(0.0, min(bid * p["cap_bid"], bid * r["ltv"]) - r["bang"])
    side = bid * tax + p["law"] + p["evict"] + p["fix"] + (p["loan_fee"] if loan > 0 else 0)
    inv = bid + side - p["dep"] - loan
    yr = rent * 12 - p["hold"] - loan * p["rate"]
    return dict(loan=loan, inv=inv, cash=yr / 12, coc=(yr / inv if inv > 0 else float("inf")), tax=tax)

def max_bid(rent, pub, reg, p=P):
    """목표 수익률과 월 순현금 하한을 동시에 맞추는 최대 낙찰가"""
    best = None
    for b in range(2000, 20001, 10):
        d = calc(b, rent, pub, reg, p)
        if d["cash"] >= p["min_cash"] and d["coc"] >= p["target"]:
            best = b
    return best

def load_env():
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return {"TELEGRAM_BOT_TOKEN": os.environ["TELEGRAM_BOT_TOKEN"], "TELEGRAM_CHAT_ID": os.environ["TELEGRAM_CHAT_ID"]}
    env = {}
    p = os.path.join(HERE, "telegram.env")
    if not os.path.exists(p): p = os.path.join(os.path.dirname(HERE), "telegram.env")
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); env[k.strip()] = v.strip()
    return env

BUTTON = json.dumps({"inline_keyboard": [[{"text": "↻ 지금 다시 조사", "callback_data": "rescan"}]]})

def tg(method, **params):
    env = load_env()
    url = "https://api.telegram.org/bot%s/%s" % (env["TELEGRAM_BOT_TOKEN"], method)
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=70) as r:
        return json.load(r)

def send_telegram(text, button=False):
    env = load_env()
    url = "https://api.telegram.org/bot%s/sendMessage" % env["TELEGRAM_BOT_TOKEN"]
    q = {"chat_id": env["TELEGRAM_CHAT_ID"], "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if button:
        q["reply_markup"] = BUTTON
    data = urllib.parse.urlencode(q).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
            ok = json.load(r).get("ok")
        print("telegram:", "ok" if ok else "fail")
    except urllib.error.HTTPError as e:
        print("telegram error:", e.code, json.loads(e.read().decode()).get("description"))

SEARCH = "https://madangs.com/search?state=10&share=1&use_type=2002%2B2003%2B2012%2B2013&addr={addr}&low_p_max={pmax}&limit=60&page={page}"
AREAS = {"서울": "11", "남양주": "41360"}
RISK_TAGS = ["선순위전세권", "지분매각", "건물만매각", "토지만매각", "법정지상권", "유치권", "선순위가처분", "선순위가등기", "대지권미등기", "분묘기지권"]
WATCH_TAGS = ["재매각", "특별매각조건", "위반건축물", "임차권등기"]

def _field(seg, key, num=False):
    m = re.search(r'"%s":(-?\d+(?:\.\d+)?|"(?:[^"\\]|\\.)*"|null|\[[^\]]*\])' % re.escape(key), seg)
    if not m: return None
    v = m.group(1)
    if v == "null": return None
    if v.startswith("["): return re.findall(r'"([^"]+)"', v)
    if v.startswith('"'): return v[1:-1]
    return float(v) if num else v

def _objects(html):
    """페이지 데이터에서 "m_code"를 가진 물건 객체 문자열들을 키 순서와 무관하게 잘라냄"""
    objs, last_end = [], -1
    for m in re.finditer(r'"m_code":"', html):
        i = m.start()
        if i < last_end: continue
        depth, j = 0, i
        while j > 0:
            c = html[j]
            if c == "}": depth += 1
            elif c == "{":
                if depth == 0: break
                depth -= 1
            j -= 1
        depth, k = 0, j
        while k < len(html):
            c = html[k]
            if c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0: break
            k += 1
        objs.append(html[j:k + 1]); last_end = k
    return objs

def fetch_listings(pmax_won=None):
    """경매마당 /search 페이지(robots 허용 경로)에서 서울·남양주 다세대·연립 진행 물건 수집. 금액 단위 만원."""
    if pmax_won is None:
        pmax_won = max_bid(70, None, "서울") * 10000
    out, seen = [], set()
    for name, code in AREAS.items():
        for page in range(1, 6):
            url = SEARCH.format(addr=code, pmax=int(pmax_won), page=page)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (personal auction alert; 1 run/day)"})
            html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore").replace('\\"', '"')
            segs = _objects(html)
            new = 0
            for seg in segs:
                code_ = _field(seg, "m_code")
                if not code_ or code_ in seen or not _field(seg, "case_num"): continue
                seen.add(code_); new += 1
                tags = _field(seg, "special_right") or []
                tags = tags if isinstance(tags, list) else []
                out.append(dict(
                    case=(_field(seg, "bubwon_short") or "") + " " + (_field(seg, "case_num") or ""),
                    addr=_field(seg, "addr") or "", use=_field(seg, "use_type") or "",
                    appraisal=round((_field(seg, "eval_price_v", True) or 0) / 10000),
                    min_price=round((_field(seg, "low_price", True) or 0) / 10000),
                    uchal=_field(seg, "m_bid_uchal") or "0", date=_field(seg, "m_bid_date") or "",
                    area=_field(seg, "m_build_area") or "", tags=tags, pub=None,
                    url="https://madangs.com" + (_field(seg, "case_url") or ""), m_code=code_,
                    share=_field(seg, "m_share_type")))
            if new == 0 or len(segs) < 50:
                break
            time.sleep(2)
    return out

def risk_of(it):
    t = it["tags"]
    hard = [x for x in RISK_TAGS if x in t] + [x for x in t if "지분" in x]
    if it.get("share") == "0,2":
        hard.append("지분물건")
    if "선순위임차인" in t and "대항력포기" not in t:
        hard.append("선순위임차인")
    return hard

RENT_STEPS = [40, 45, 50, 55, 60, 65, 70]

def screen(items):
    """최저가로 낙찰 시 목표(15%·월 20만)를 맞추는 데 필요한 최소 월세를 붙여 반환"""
    hits = []
    for it in items:
        reg = region_of(it["addr"])
        if not reg or it["min_price"] <= 0 or risk_of(it):
            continue
        if it["date"] and it["date"] <= time.strftime("%Y-%m-%d"):  # 오늘·지난 매각일 제외
            continue
        for r in RENT_STEPS:
            cap = max_bid(r, it.get("pub"), reg)
            if cap and it["min_price"] <= cap:
                hits.append((it, reg, r, cap, calc(it["min_price"], r, it.get("pub"), reg)))
                break
    hits.sort(key=lambda h: (h[2], h[0]["date"]))
    return hits

import html as _html
from datetime import date as _date

def _won(m):
    m = int(round(m))
    if m >= 10000:
        e, r = divmod(m, 10000)
        return "%d억" % e + (" %s만" % f"{r:,}" if r else "")
    return f"{m:,}만"

def _short_addr(a):
    for p in ["서울특별시 ", "경기도 남양주시 "]:
        a = a.replace(p, "")
    a = re.sub(r"\s+", " ", a).strip()
    return a

def _when(d):
    try:
        y, m, dd = map(int, d.split("-")); dt = _date(y, m, dd)
        left = (dt - _date.today()).days
        return "%d/%d(%s) D-%d" % (m, dd, "월화수목금토일"[dt.weekday()], left)
    except Exception:
        return d

def fmt(hits, new_codes=None):
    E = _html.escape
    if not hits:
        return ["<b>경매 퀀트 알림</b>\n오늘은 기준(수익률 15%·월 순현금 20만↑)에 맞는 새 물건이 없습니다."]
    n_seoul = sum(1 for h in hits if h[1] == "서울")
    head = ("<b>경매 퀀트 알림 · %d건</b>\n서울 %d · 남양주 %d\n"
            "<i>최저가 낙찰·무대출 기준 (보증금 1,000 · 수리 500)</i>") % (len(hits), n_seoul, len(hits) - n_seoul)
    blocks = []
    for i, (it, reg, r, cap, d) in enumerate(hits, 1):
        badges = []
        if new_codes is not None and it["m_code"] in new_codes: badges.append("NEW")
        if "지하" in it["addr"] or "비0" in it["addr"]: badges.append("반지하")
        warn = [t for t in it["tags"] if t in WATCH_TAGS + ["대항력포기", "선순위임차인"]]
        rate = (it["min_price"] / it["appraisal"] * 100) if it["appraisal"] else 0
        lines = [
            "━━━━━━━━━━━━",
            "<b>%d. %s</b>%s" % (i, E(_short_addr(it["addr"])), ("  [" + "·".join(badges) + "]") if badges else ""),
            "%s · %s · %s" % (E(it["case"]), E(reg.replace("_", " ")), E(it["use"])),
            "매각 <b>%s</b>" % _when(it["date"]),
            "",
            "최저 <b>%s</b>  (감정 %s의 %d%% · 유찰 %s회)" % (_won(it["min_price"]), _won(it["appraisal"]), round(rate), it["uchal"]),
            "▶ 월세 <b>%d만</b> 받으면 수익률 <b>%.1f%%</b>" % (r, d["coc"] * 100),
            "   실투자 %s · 월 +%d만 · 입찰상한 %s" % (_won(d["inv"]), round(d["cash"]), _won(cap)),
        ]
        if warn:
            lines.append("주의: " + E(", ".join(warn)))
        lines.append('<a href="%s">경매마당에서 보기</a>' % E(it["url"]))
        blocks.append("\n".join(lines))
    msgs, cur = [], head
    for b in blocks:
        if len(cur) + len(b) + 2 > 3800:
            msgs.append(cur); cur = b
        else:
            cur += "\n" + b
    msgs.append(cur)
    return msgs

SEEN_FILE = os.path.join(HERE, "seen.json")

def run(full=False):
    """full=False: 새 물건만 / full=True: 지금 조건에 맞는 전체(새 물건 NEW 표시)"""
    items = fetch_listings()
    hits = screen(items)
    try:
        seen = set(json.load(open(SEEN_FILE, encoding="utf-8")))
    except Exception:
        seen = set()
    codes = {h[0]["m_code"] + ":" + str(h[0]["min_price"]) for h in hits}
    new_codes = {c.split(":")[0] for c in codes - seen}
    send = hits if full else [h for h in hits if h[0]["m_code"] in new_codes]
    msgs = fmt(send, new_codes)
    if full:
        msgs[0] = msgs[0].replace("<b>경매 퀀트 알림", "<b>[다시 조사 %s] 경매 퀀트 알림" % time.strftime("%H:%M"), 1)
    for i, m in enumerate(msgs):
        send_telegram(m, button=(i == len(msgs) - 1))
    json.dump(sorted(seen | codes), open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    print("fetched", len(items), "hits", len(hits), "sent", len(send))

STATE_FILE = os.path.join(HERE, "state.json")
DAILY_AT = "08:50"  # KST, 이 시각 이후 첫 확인 때 하루 1번 정기 알림

def _state():
    try: return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception: return {"offset": 0, "last_daily": ""}

def _fresh(args):
    """저장소 최신 코드를 받아 새 프로세스로 실행 → 코드 수정이 버튼에 바로 반영"""
    import subprocess
    subprocess.run(["git", "pull", "--rebase", "--autostash", "-q"], cwd=HERE)
    r = subprocess.run([sys.executable, os.path.join(HERE, "alert.py")] + args, cwd=HERE)
    if r.returncode != 0:
        raise RuntimeError("조사 스크립트 실패 (code %s)" % r.returncode)

def listen(seconds):
    """버튼/명령을 기다리며 seconds 동안 대기. 정기 알림 시각이 지나면 하루 1번 실행."""
    os.environ["TZ"] = "Asia/Seoul"; time.tzset()
    st = _state(); end = time.time() + seconds
    chat = str(load_env()["TELEGRAM_CHAT_ID"])
    while time.time() < end:
        today = time.strftime("%Y-%m-%d")
        if st.get("last_daily") != today and time.strftime("%H:%M") >= DAILY_AT:
            try: _fresh([])
            except Exception as e: send_telegram("경매 알림 실행 오류: %s" % _html.escape(str(e)[:200]), button=True)
            st["last_daily"] = today; json.dump(st, open(STATE_FILE, "w"))
        wait = int(max(1, min(50, end - time.time() - 5)))
        try:
            ups = tg("getUpdates", offset=st.get("offset", 0), timeout=wait,
                     allowed_updates=json.dumps(["message", "callback_query"])).get("result", [])
        except Exception as e:
            print("poll error", type(e).__name__); time.sleep(10); continue
        rescan = False
        for u in ups:
            st["offset"] = u["update_id"] + 1
            cq = u.get("callback_query")
            if cq and str(cq.get("message", {}).get("chat", {}).get("id")) == chat and cq.get("data") == "rescan":
                tg("answerCallbackQuery", callback_query_id=cq["id"], text="지금 시점으로 다시 조사합니다")
                rescan = True
            m = u.get("message")
            if m and str(m.get("chat", {}).get("id")) == chat and (m.get("text", "").strip() in ("/scan", "/start", "조사", "다시조사", "다시 조사")):
                rescan = True
        json.dump(st, open(STATE_FILE, "w"))
        if rescan:
            send_telegram("조사 중입니다… (약 30초)")
            try: _fresh(["--full"])
            except Exception as e: send_telegram("다시 조사 오류: %s" % _html.escape(str(e)[:200]), button=True)
    json.dump(st, open(STATE_FILE, "w"))

def bind_chat():
    """봇에게 메시지를 보낸 개인 채팅 ID를 찾아 telegram.env에 저장"""
    env = load_env()
    d = json.load(urllib.request.urlopen("https://api.telegram.org/bot%s/getUpdates" % env["TELEGRAM_BOT_TOKEN"], timeout=20))
    ids = {u["message"]["chat"]["id"] for u in d.get("result", []) if u.get("message", {}).get("chat", {}).get("type") == "private"}
    if len(ids) != 1:
        print("private chats found:", len(ids)); return False
    p = os.path.join(HERE, "telegram.env"); s = open(p, encoding="utf-8").read()
    s = re.sub(r"(?m)^TELEGRAM_CHAT_ID=.*$", "TELEGRAM_CHAT_ID=%d" % ids.pop(), s)
    open(p, "w", encoding="utf-8").write(s); print("chat id saved"); return True

if __name__ == "__main__":
    if "--bind" in sys.argv:
        bind_chat() and send_telegram("경매 퀀트 알림 연결 완료. 매일 아침 조건에 맞는 새 물건을 보내드립니다.")
    elif "--test" in sys.argv:
        send_telegram("경매 퀀트 알림 연결 테스트입니다.")
    elif "--selftest" in sys.argv:
        for reg in REGION:
            print(reg, {r: max_bid(r, 9000, reg) for r in RENTS}, calc(10000, 70, 9400, reg))
    elif "--listen" in sys.argv:
        listen(int(sys.argv[sys.argv.index("--listen") + 1]))
    elif "--full" in sys.argv:
        run(full=True)
    elif "--preview" in sys.argv:
        for m in fmt(screen(fetch_listings())): send_telegram(m)
    elif "--dry" in sys.argv:
        hits = screen(fetch_listings())
        for m in fmt(hits): print(m); print("-----")
    else:
        run()
