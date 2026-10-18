"""경매 월세 퀀트 알림 (서울·남양주)
사용: python3 alert.py --test          → 텔레그램 연결 테스트
      python3 alert.py                 → 월세 퀀트: 새 물건만 발송
      python3 alert.py --full          → 월세 퀀트: 조건 충족 전체 발송
      python3 alert.py --gaechuk       → 개축 퀀트: 새 물건만 발송
      python3 alert.py --gaechuk-full  → 개축 퀀트: 조건 충족 전체 발송
      python3 alert.py --gaechuk-dry   → 개축 퀀트: 발송 없이 화면 출력
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

BUTTON = json.dumps({"inline_keyboard": [[{"text": "↻ 월세 퀀트", "callback_data": "rescan"},
                                           {"text": "🏗 개축 퀀트", "callback_data": "gaechuk"}]]})

def tg(method, **params):
    env = load_env()
    url = "https://api.telegram.org/bot%s/%s" % (env["TELEGRAM_BOT_TOKEN"], method)
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=70) as r:
        return json.load(r)

def _answer(cq, text):
    """버튼 눌림 응답. 오래된 버튼(약 15분 경과)은 텔레그램이 400을 주므로 무시하고 조사는 계속"""
    try: tg("answerCallbackQuery", callback_query_id=cq["id"], text=text)
    except Exception as e: print("answerCallbackQuery skip", type(e).__name__)

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

# =====================================================================
# 실거래 월세 검증: 국토교통부 연립다세대 전월세 실거래가(data.go.kr)로
# 같은 동·비슷한 전용면적의 최근 월세 중간값이 필요 월세 이상인 물건만 추천
# =====================================================================
RENT_API = "https://apis.data.go.kr/1613000/RTMSDataSvcRHRent/getRTMSDataSvcRHRent"
RENT_MONTHS = 12        # 최근 몇 개월 거래를 볼지
RENT_AREA_TOL = 0.20    # 전용면적 ±20% (최소 ±7㎡)
RENT_MIN_DEALS = 3      # 동 단위 월세 거래가 이 건수 미만이면 '거래 부족'으로 제외
RENT_CONV = 0.06        # 전월세 전환율(연) — 보증금 차이를 월세로 환산 (보증금 P["dep"] 기준)
RENT_CACHE = os.path.join(HERE, "rent.json")
LAWD = {"종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200", "광진구": "11215", "동대문구": "11230",
        "중랑구": "11260", "성북구": "11290", "강북구": "11305", "도봉구": "11320", "노원구": "11350", "은평구": "11380",
        "서대문구": "11410", "마포구": "11440", "양천구": "11470", "강서구": "11500", "구로구": "11530", "금천구": "11545",
        "영등포구": "11560", "동작구": "11590", "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710",
        "강동구": "11740", "남양주시": "41360"}
RENT_STATS = {}

def _rent_key():
    k = os.environ.get("DATA_GO_KR_KEY", "")
    if not k:
        for p in (os.path.join(HERE, "telegram.env"), os.path.join(os.path.dirname(HERE), ".env")):
            try:
                for line in open(p, encoding="utf-8"):
                    if line.strip().startswith("DATA_GO_KR_KEY="): k = line.split("=", 1)[1].strip()
            except OSError: pass
            if k: break
    return urllib.parse.unquote(k) if "%" in k else k   # 'Encoding' 키를 넣어도 동작

def _locality(addr):
    """주소 → (시군구 코드, 동/읍/면 이름)"""
    t = addr.split()
    lawd = next((LAWD[x] for x in t[:3] if x in LAWD), None)
    umd = next((x for x in t[1:4] if re.search(r"(동|읍|면|가)$", x) and x not in LAWD), None)
    return lawd, umd

def _rent_fetch(lawd, ym, key):
    rows, page = [], 1
    while True:
        q = urllib.parse.urlencode(dict(serviceKey=key, LAWD_CD=lawd, DEAL_YMD=ym, pageNo=page, numOfRows=1000))
        x = urllib.request.urlopen(RENT_API + "?" + q, timeout=30).read().decode("utf-8", "ignore")
        code = re.search(r"<resultCode>\s*(\w+)\s*</resultCode>", x)
        if not code or code.group(1).strip("0"):
            msg = re.search(r"<(?:resultMsg|returnAuthMsg)>([^<]*)", x)
            raise RuntimeError("rent api: %s" % (msg.group(1) if msg else "응답 형식 오류"))
        items = re.findall(r"<item>(.*?)</item>", x, re.S)
        for it in items:
            g = lambda tag: (re.search(r"<%s>\s*([^<]*?)\s*</%s>" % (tag, tag), it) or [None, ""])[1]
            rent = _num(g("monthlyRent"))
            if rent <= 0: continue   # 전세 제외
            rows.append([g("umdNm"), _num(g("excluUseAr")), _num(g("deposit")), rent, int(_num(g("floor")) or 0)])
        tc = re.search(r"<totalCount>\s*(\d+)", x)
        if not items or page * 1000 >= int(tc.group(1) if tc else 0): break
        page += 1; time.sleep(0.3)
    return rows

def _months(n):
    y, m = map(int, time.strftime("%Y %m").split()); out = []
    for _ in range(n):
        out.append("%04d%02d" % (y, m)); m -= 1
        if m == 0: y, m = y - 1, 12
    return out

def _rent_rows(lawd, key, cache):
    rows, today = [], time.strftime("%Y-%m-%d")
    week_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
    for i, ym in enumerate(_months(RENT_MONTHS)):
        c = cache.get(lawd + ":" + ym)
        if not c or (i < 3 and c["t"] < week_ago):   # 최근 3개월은 신고 지연(30일)이 있어 주 1회 다시 받음
            c = {"t": today, "rows": _rent_fetch(lawd, ym, key)}; cache[lawd + ":" + ym] = c; time.sleep(0.3)
        rows += c["rows"]
    return rows

def market_rent(it, key, cache):
    """같은 동·비슷한 면적·같은 층 유형(지하/지상) 월세 실거래 중간값 (보증금 P['dep'] 기준 환산)"""
    lawd, umd = _locality(it["addr"])
    area = _num(it["area"])
    if not lawd or not umd or area <= 0: return None
    tol = max(area * RENT_AREA_TOL, 7)
    under = bool(re.search(r"지하|비0", it["addr"]))
    eq = sorted(r[3] + (r[2] - P["dep"]) * RENT_CONV / 12 for r in _rent_rows(lawd, key, cache)
                if r[0].split()[:1] == [umd] and abs(r[1] - area) <= tol and ((r[4] < 0) == under))
    if len(eq) < RENT_MIN_DEALS: return dict(n=len(eq), umd=umd)
    n = len(eq); mid = eq[n // 2] if n % 2 else (eq[n // 2 - 1] + eq[n // 2]) / 2
    return dict(n=n, umd=umd, rent=mid, lo=eq[n // 4], hi=eq[(n * 3) // 4], amin=area - tol, amax=area + tol)


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
    hits = _verify_rent(hits)
    hits.sort(key=lambda h: (h[2], h[0]["date"]))
    return hits

def _verify_rent(hits):
    """실거래 월세 중간값이 필요 월세 이상인 물건만 남기고, 수익률을 실거래 월세로 다시 계산"""
    key = _rent_key(); RENT_STATS.clear(); RENT_STATS.update(on=bool(key), cand=len(hits), low=0, few=0, err=0)
    if not key: return [h + (None,) for h in hits]
    try: cache = json.load(open(RENT_CACHE, encoding="utf-8"))
    except Exception: cache = {}
    out = []
    for it, reg, r, cap, d in hits:
        try: mk = market_rent(it, key, cache)
        except Exception as e:
            print("rent fail", type(e).__name__, str(e)[:80]); RENT_STATS["err"] += 1; continue
        if not mk or "rent" not in mk: RENT_STATS["few"] += 1; continue
        real = int(round(mk["rent"]))
        if real < r: RENT_STATS["low"] += 1; continue
        out.append((it, reg, real, max_bid(real, it.get("pub"), reg) or cap, calc(it["min_price"], real, it.get("pub"), reg), mk))
    keep = set(_months(RENT_MONTHS))
    cache = {k: v for k, v in cache.items() if k.split(":")[1] in keep}
    json.dump(cache, open(RENT_CACHE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return out

import html as _html
from datetime import date as _date

def _won(m):
    m = int(round(m))
    if m >= 10000:
        e, r = divmod(m, 10000)
        return "%d억" % e + (" %s만" % f"{r:,}" if r else "")
    return f"{m:,}만"

def _rent_note():
    s = RENT_STATS
    if not s or not s.get("on"): return "\n실거래 월세 확인 꺼짐 (DATA_GO_KR_KEY 없음) — 월세는 가정값"
    t = "\n실거래 월세 확인: 후보 %d건 중 시세 미달 %d · 거래 부족 %d 제외" % (s["cand"], s["low"], s["few"])
    return t + (" · 조회 실패 %d" % s["err"] if s["err"] else "")

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
        return ["<b>경매 퀀트 알림</b>\n오늘은 기준(수익률 15%·월 순현금 20만↑)에 맞는 새 물건이 없습니다." + _rent_note()]
    n_seoul = sum(1 for h in hits if h[1] == "서울")
    head = ("<b>경매 퀀트 알림 · %d건</b>\n서울 %d · 남양주 %d\n"
            "<i>최저가 낙찰·무대출 기준 (보증금 1,000 · 수리 500)%s</i>") % (len(hits), n_seoul, len(hits) - n_seoul, _rent_note())
    blocks = []
    for i, (it, reg, r, cap, d, mk) in enumerate(hits, 1):
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
            ("▶ 실거래 월세 <b>%d만</b>이면 수익률 <b>%.1f%%</b>" if mk else "▶ 월세 <b>%d만</b> 받으면 수익률 <b>%.1f%%</b>") % (r, d["coc"] * 100),
            "   실투자 %s · 월 +%d만 · 입찰상한 %s" % (_won(d["inv"]), round(d["cash"]), _won(cap)),
        ]
        if mk:
            lines.append("   %s 전용 %d~%d㎡%s 최근 %d개월 월세 %d건 · 중간 %d만 (%d~%d만)" % (
                E(mk["umd"]), round(mk["amin"]), round(mk["amax"]), " 지하" if re.search(r"지하|비0", it["addr"]) else "",
                RENT_MONTHS, mk["n"], round(mk["rent"]), round(mk["lo"]), round(mk["hi"])))
        if warn:
            lines.append("주의: " + E(", ".join(warn)))
        lines.append(E(it["url"]))   # 텍스트 링크(<a>)는 텔레그램이 확인창을 띄워서 URL 그대로 노출
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

# =====================================================================
# 개축 퀀트: 건축물대장 용적률이 현행 상한을 넘는 '기존 건축물 특례' 후보
# (국토계획법 시행령 제93조 — 법령·계획 변경으로 부적합해진 적법 건물은 종전 규모로 개축 가능)
# =====================================================================
G_SEARCH = "https://madangs.com/search?state=10&share=1&use_type=2004%2B2005%2B2006%2B2007%2B3003%2B4002&addr={addr}&low_p_max={pmax}&limit=60&page={page}"
G_AREAS = {"서울": "11", "경기": "41"}
# ---- 예산 (단위: 만원) ----
G_BUY_MAX = 35000      # 최저가 상한 (매입 3억 내외)
G_COST_PER_PY = 700    # 개축 공사비 평당 단가 가정
G_BUILD_MAX = 30000    # 기존 연면적 그대로 개축 시 공사비 상한 (2억 내외 + 여유)
G_SHOW_MAX = 20        # 다시 조사 때 최대 표시 건수
# 서울시 도시계획조례 상한: (용도지역, 용적률%, 건폐율%)
SEOUL_CAP = [("제1종전용주거지역", 100, 50), ("제2종전용주거지역", 120, 40), ("제1종일반주거지역", 150, 60),
             ("제2종일반주거지역", 200, 60), ("제3종일반주거지역", 250, 50), ("준주거지역", 400, 60),
             ("중심상업지역", 1000, 60), ("일반상업지역", 800, 60), ("근린상업지역", 600, 60), ("유통상업지역", 600, 60),
             ("전용공업지역", 200, 60), ("일반공업지역", 200, 60), ("준공업지역", 400, 60),
             ("보전녹지지역", 50, 20), ("생산녹지지역", 50, 20), ("자연녹지지역", 50, 20)]
# 서울 외 지역: 국토계획법 시행령 법정 상한 (시·군 조례는 이보다 낮거나 같음 → 초과분은 보수적으로 계산됨)
STAT_CAP = [("제1종전용주거지역", 100, 50), ("제2종전용주거지역", 150, 50), ("제1종일반주거지역", 200, 60),
            ("제2종일반주거지역", 250, 60), ("제3종일반주거지역", 300, 50), ("준주거지역", 500, 70),
            ("중심상업지역", 1500, 90), ("일반상업지역", 1300, 80), ("근린상업지역", 900, 70), ("유통상업지역", 1100, 80),
            ("전용공업지역", 300, 70), ("일반공업지역", 350, 70), ("준공업지역", 400, 70),
            ("보전녹지지역", 80, 20), ("생산녹지지역", 100, 20), ("자연녹지지역", 100, 20),
            ("계획관리지역", 100, 40), ("생산관리지역", 80, 20), ("보전관리지역", 80, 20),
            ("농림지역", 80, 20), ("자연환경보전지역", 80, 20)]
ZONE_NAMES = {c[0] for c in STAT_CAP}
TEMP_FAR = {"제2종일반주거지역": 250, "제3종일반주거지역": 300}   # 서울 소규모 건축 한시 완화
TEMP_UNTIL = "2028-05-18"
G_PRE_RATIO = 0.2      # 목록 단계: 경매 건물면적/토지면적 이 값 미만은 상세 조회 생략
G_MIN_EXCESS = 10      # ㎡, 용적률 초과분 최소
G_MIN_BCR_EXCESS = 5   # ㎡, 건폐율(바닥면적) 초과분 최소
BAD_ROAD = ("맹지", "세로한면(불)", "세로각지(불)")  # 차가 못 들어가는 좁은 길·맹지 → '좁은 길'로 표시해 맨 아래 (신축이 막혀 개축 특례 후보)
G_MAX_YEAR = "2003"    # 용도지역 종세분화(2003.7) 이전 사용승인만 — 이후 건물의 초과분은 인센티브·위반 가능성이 커 제외
G_CACHE = os.path.join(HERE, "gaechuk.json")
UA = {"User-Agent": "Mozilla/5.0 (personal auction alert; few runs/day)"}

def _get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore").replace('\\"', '"')

def _grab_array(h, key):
    i = h.find(key)
    if i < 0: return None
    s = i + len(key) - 1
    dep, ins, esc = 0, False, False
    for k in range(s, len(h)):
        c = h[k]
        if ins:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': ins = False
            continue
        if c == '"': ins = True
        elif c in "[{": dep += 1
        elif c in "]}":
            dep -= 1
            if dep == 0: return h[s:k + 1]
    return None

def _num(v):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v or "").replace(",", ""))
    return float(m.group()) if m else 0.0

def g_fetch_listings():
    out, seen = [], set()
    for name, code in G_AREAS.items():
        for page in range(1, 30):
            html = _get(G_SEARCH.format(addr=code, page=page, pmax=G_BUY_MAX * 10000))
            segs = _objects(html); new = 0
            for seg in segs:
                c = _field(seg, "m_code")
                if not c or c in seen or not _field(seg, "case_num"): continue
                seen.add(c); new += 1
                tags = _field(seg, "special_right") or []
                out.append(dict(
                    case=(_field(seg, "bubwon_short") or "") + " " + (_field(seg, "case_num") or ""),
                    addr=_field(seg, "addr") or "", use=_field(seg, "use_type") or "",
                    appraisal=round((_field(seg, "eval_price_v", True) or 0) / 10000),
                    min_price=round((_field(seg, "low_price", True) or 0) / 10000),
                    uchal=_field(seg, "m_bid_uchal") or "0", date=_field(seg, "m_bid_date") or "",
                    land=_field(seg, "m_land_area", True) or 0, build=_field(seg, "m_build_area", True) or 0,
                    tags=tags if isinstance(tags, list) else [], m_code=c, share=_field(seg, "m_share_type"),
                    url="https://madangs.com" + (_field(seg, "case_url") or "")))
            if new == 0 or len(segs) < 50: break
            time.sleep(1.5)
    return out

def g_detail(m_code):
    """사건 상세에서 건축물대장·토지대장·지역지구를 읽음"""
    items = json.loads(_grab_array(_get("https://madangs.com/caview?m_code=" + m_code), '"items":{"items":['))
    lands = [it for it in items if str(it.get("i_class_code")) == "1"]
    regs = [(it.get("item_info") or {}).get("건물대장") for it in items]
    regs = [r for r in regs if r]
    zones = []
    for it in lands:
        for z in (it.get("item_info") or {}).get("지역지구", []):
            if z in ZONE_NAMES and z not in zones: zones.append(z)
    years = sorted(re.sub(r"\D", "", r.get("사용승인일", ""))[:4] for r in regs if re.search(r"\d{4}", r.get("사용승인일", "")))
    roads = [((it.get("item_info") or {}).get("토지대장") or {}).get("도로접면", "") for it in lands]
    return dict(land=sum(_num(it.get("land_area_share") or it.get("land_area_float")) for it in lands), road=[r for r in roads if r],
                zones=zones, n_bld=len(regs),
                reg_total=sum(_num(r.get("연면적")) for r in regs),
                reg_far=[_num(r.get("용적률")) for r in regs], reg_bcr=[_num(r.get("건폐율")) for r in regs],
                floors=[r.get("층수", "") for r in regs], year=(years[0] if years else ""),
                t=time.strftime("%Y-%m-%d"))

def g_eval(it, d):
    """현행 상한 대비 대장상 초과분(=개축으로 지킬 수 있는 면적) 계산: 용적률(연면적) + 건폐율(바닥면적)"""
    land = d["land"] or it["land"]
    if land <= 0 or not d["zones"] or d["n_bld"] == 0 or d["reg_total"] <= 0: return None
    seoul = it["addr"].startswith("서울")
    caps = [c for c in (SEOUL_CAP if seoul else STAT_CAP) if c[0] in d["zones"]]
    if not caps: return None
    zone, cap_far, cap_bcr = max(caps, key=lambda c: c[1])  # 걸친 대지는 높은 쪽 기준(보수적)
    one = d["n_bld"] == 1
    if one and d["reg_far"][0] > 0: far, est = d["reg_far"][0], False
    else: far, est = d["reg_total"] / land * 100, True     # 대장 용적률이 없으면 연면적/대지 추정(지하 포함 가능)
    bcr, bcr_est = None, False
    if one and d["reg_bcr"][0] > 0: bcr = d["reg_bcr"][0]
    elif all(re.match(r"\s*1층\s*/\s*(-|0층)?\s*$", f or "") for f in d["floors"]):
        bcr, bcr_est = d["reg_total"] / land * 100, True   # 지상 1층·지하 없음 → 연면적 = 바닥면적
    excess = (far - cap_far) / 100 * land
    bexcess = ((bcr - cap_bcr) / 100 * land) if bcr else 0
    temp = TEMP_FAR.get(zone) if seoul else None
    return dict(zone=zone, cap_far=cap_far, cap_bcr=cap_bcr, far=far, est=est, bcr=bcr, bcr_est=bcr_est, land=land,
                excess=excess, bexcess=bexcess, temp=temp, excess_temp=((far - temp) / 100 * land) if temp else None,
                year=d["year"], multi=len(d["zones"]) > 1, n_bld=d["n_bld"], seoul=seoul, total=d["reg_total"],
                cost=d["reg_total"] / 3.3058 * G_COST_PER_PY,
                road=next((r for r in d.get("road", []) if r not in BAD_ROAD), None),
                road_bad=bool(d.get("road")) and all(r in BAD_ROAD for r in d["road"]), roads=d.get("road", []))

def g_screen(items, log=print):
    try: cache = json.load(open(G_CACHE, encoding="utf-8"))
    except Exception: cache = {}
    today = time.strftime("%Y-%m-%d"); hits = []; fetched = 0
    for it in items:
        if it["date"] and it["date"] <= today: continue
        if "위반건축물" in it["tags"] or risk_of(it): continue
        if it["land"] <= 0 or it["build"] / it["land"] < G_PRE_RATIO: continue
        if re.search(r"\d+층|\d+호", it["addr"]): continue   # 구분건물(호실) 제외
        d = cache.get(it["m_code"])
        if not d or "road" not in d or d.get("t", "") < time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400)):
            try:
                d = g_detail(it["m_code"]); cache[it["m_code"]] = d; fetched += 1; time.sleep(1.2)
                if fetched % 15 == 0: json.dump(cache, open(G_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception as e:
                log("detail fail %s %s" % (it["m_code"], type(e).__name__)); continue
        e = g_eval(it, d)
        if not e or (e["year"] and e["year"] > G_MAX_YEAR) or e["cost"] > G_BUILD_MAX: continue
        if e["excess"] >= G_MIN_EXCESS or e["bexcess"] >= G_MIN_BCR_EXCESS or e["road_bad"]:
            hits.append((it, e))
    json.dump(cache, open(G_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    tier = lambda e: 2 if e["road_bad"] else (0 if e["road"] else 1)   # 좋은 길 → 도로 미확인 → 좁은 길
    hits.sort(key=lambda h: (tier(h[1]), not h[0]["addr"].startswith("서울"), -(max(h[1]["excess"], 0) + max(h[1]["bexcess"], 0)), h[0]["min_price"]))
    log("gaechuk: listings %d, detail fetched %d, hits %d" % (len(items), fetched, len(hits)))
    return hits

def _split(head, blocks):
    msgs, cur = [], head
    for b in blocks:
        if len(cur) + len(b) + 2 > 3800: msgs.append(cur); cur = b
        else: cur += "\n" + b
    msgs.append(cur)
    return msgs

def _py(m2): return m2 / 3.3058

def g_fmt(hits, new_codes=None, total=None):
    E = _html.escape
    if not hits:
        extra = (" (현재 조건 충족 %d건 — [개축 퀀트] 버튼으로 전체 보기)" % total) if total else ""
        return ["<b>개축 퀀트</b>\n오늘은 새로 걸린 물건이 없습니다.%s" % extra]
    good = [h for h in hits if not h[1]["road_bad"]]   # 좋은 길(·미확인)은 모두, 좁은 길은 남는 자리만
    more = len(hits) - max(G_SHOW_MAX, len(good))
    hits = hits[:max(G_SHOW_MAX, len(good))]
    head = ("<b>개축 퀀트 · %d건</b>%s\n"
            "<i>서울·경기 최저가 %s 이하 · 2003년 이전 승인 · 대장 용적률/건폐율이 현행 상한 초과 또는 좁은 길(맹지·세로불) "
            "(위반건축물·지분 제외) · 좋은 길 먼저, 좁은 길은 아래 · 개축비는 기존 연면적 × 평당 %d만 가정\n"
            "서울은 조례, 경기는 법정상한 기준. 특례 적용은 건축사 확인 필요</i>") % (
            len(hits) + max(more, 0), (" (상위 %d건 표시)" % len(hits)) if more > 0 else "", _won(G_BUY_MAX), G_COST_PER_PY)
    blocks = []
    for i, (it, e) in enumerate(hits, 1):
        if e["road_bad"] and (i == 1 or not hits[i - 2][1]["road_bad"]):
            blocks.append("━━━━━━━━━━━━\n<b>▼ 좁은 길 물건 (맹지·세로불)</b>")
        badge = "  [NEW]" if new_codes is not None and it["m_code"] in new_codes else ""
        rate = (it["min_price"] / it["appraisal"] * 100) if it["appraisal"] else 0
        cap_name = "현행" if e["seoul"] else "법정상한"
        lines = [
            "━━━━━━━━━━━━",
            "<b>%d. %s</b>%s" % (i, E(_short_addr(it["addr"])), badge),
            "%s · %s%s" % (E(it["case"]), E(it["use"]), (" · %s년 승인" % e["year"]) if e["year"] else ""),
            "매각 <b>%s</b>" % _when(it["date"]),
            "최저 <b>%s</b>  (감정 %s의 %d%% · 유찰 %s회)" % (_won(it["min_price"]), _won(it["appraisal"]), round(rate), it["uchal"]),
            "%s · 대지 %d㎡(%.0f평) · 대장 연면적 %d㎡(%.0f평)%s" % (E(e["zone"].replace("지역", "")), round(e["land"]), _py(e["land"]),
                                                       round(e["total"]), _py(e["total"]), " · 용도지역 2개" if e["multi"] else ""),
        ]
        if e["excess"] >= G_MIN_EXCESS:
            t = "▶ 용적률 <b>%d%%%s</b> → %s %d%% · 연면적 <b>+%d㎡(%.0f평)</b> 보존" % (
                round(e["far"]), "(추정)" if e["est"] else "", cap_name, e["cap_far"], round(e["excess"]), _py(e["excess"]))
            if e["temp"]:
                t += ("  (한시 %d%% 대비 +%d㎡)" % (e["temp"], round(e["excess_temp"]))) if e["excess_temp"] > 0 else "  (한시 %d%% 기준으론 신축이 더 큼)" % e["temp"]
            lines.append(t)
        if e["bexcess"] >= G_MIN_BCR_EXCESS:
            lines.append("▶ 건폐율 <b>%d%%%s</b> → %s %d%% · 바닥 <b>+%d㎡(%.0f평)</b> 보존" % (
                round(e["bcr"]), "(추정)" if e["bcr_est"] else "", cap_name, e["cap_bcr"], round(e["bexcess"]), _py(e["bexcess"])))
        if e["road_bad"]:
            lines.append("▶ <b>좁은 길</b> %s — 신축은 접도·건축선 후퇴로 막히거나 줄지만 기존 규모 개축은 가능성 · 주차 추가 의무 없음" % E(", ".join(dict.fromkeys(e["roads"]))))
        else:
            lines.append("도로 %s" % (E(e["road"]) if e["road"] else "미확인 (토지대장에 도로접면 없음 — 지도로 확인)"))
        lines.append("개축비 약 <b>%s</b> (기존 %.0f평 그대로)" % (_won(e["cost"]), _py(e["total"])))
        if e["n_bld"] > 1: lines.append("건물 %d동 합산" % e["n_bld"])
        warn = [t for t in it["tags"] if t in WATCH_TAGS + ["선순위임차인", "대항력포기"]]
        if warn: lines.append("주의: " + E(", ".join(warn)))
        lines.append(E(it["url"]))   # 텍스트 링크(<a>)는 텔레그램이 확인창을 띄워서 URL 그대로 노출
        blocks.append("\n".join(lines))
    return _split(head, blocks)

def g_run(full=False, dry=False):
    hits = g_screen(g_fetch_listings())
    try: seen = set(json.load(open(SEEN_FILE, encoding="utf-8")))
    except Exception: seen = set()
    codes = {"G:%s:%s" % (h[0]["m_code"], h[0]["min_price"]) for h in hits}
    new_codes = {c.split(":")[1] for c in codes - seen}
    send = hits if full else [h for h in hits if h[0]["m_code"] in new_codes]
    msgs = g_fmt(send, new_codes, total=len(hits))
    if full: msgs[0] = msgs[0].replace("<b>개축 퀀트", "<b>[다시 조사 %s] 개축 퀀트" % time.strftime("%H:%M"), 1)
    if dry:
        for m in msgs: print(m); print("-----")
        return
    for i, m in enumerate(msgs):
        send_telegram(m, button=(i == len(msgs) - 1))
    json.dump(sorted(seen | codes), open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False)

STATE_FILE = os.path.join(HERE, "state.json")
DAILY_AT = "08:50"    # KST, 오전: 월세 퀀트 새 물건
G_DAILY_AT = "13:00"  # KST, 오후: 개축 퀀트 새 물건

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
        if st.get("last_gaechuk") != today and time.strftime("%H:%M") >= G_DAILY_AT:
            try: _fresh(["--gaechuk"])
            except Exception as e: send_telegram("개축 알림 실행 오류: %s" % _html.escape(str(e)[:200]), button=True)
            st["last_gaechuk"] = today; json.dump(st, open(STATE_FILE, "w"))
        wait = int(max(1, min(50, end - time.time() - 5)))
        try:
            ups = tg("getUpdates", offset=st.get("offset", 0), timeout=wait,
                     allowed_updates=json.dumps(["message", "callback_query"])).get("result", [])
        except Exception as e:
            print("poll error", type(e).__name__); time.sleep(10); continue
        rescan = gaechuk = False
        for u in ups:
            st["offset"] = u["update_id"] + 1
            cq = u.get("callback_query")
            if cq and str(cq.get("message", {}).get("chat", {}).get("id")) == chat and cq.get("data") == "rescan":
                _answer(cq, "지금 시점으로 다시 조사합니다")
                rescan = True
            if cq and str(cq.get("message", {}).get("chat", {}).get("id")) == chat and cq.get("data") == "gaechuk":
                _answer(cq, "개축 퀀트를 지금 시점으로 조사합니다")
                gaechuk = True
            m = u.get("message")
            if m and str(m.get("chat", {}).get("id")) == chat and (m.get("text", "").strip() in ("/scan", "/start", "조사", "다시조사", "다시 조사")):
                rescan = True
            if m and str(m.get("chat", {}).get("id")) == chat and (m.get("text", "").strip() in ("/gaechuk", "개축", "개축조사", "개축 조사")):
                gaechuk = True
        json.dump(st, open(STATE_FILE, "w"))
        if gaechuk:
            send_telegram("개축 퀀트 조사 중입니다… (1~3분)")
            try: _fresh(["--gaechuk-full"])
            except Exception as e: send_telegram("개축 조사 오류: %s" % _html.escape(str(e)[:200]), button=True)
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
        bind_chat() and send_telegram("경매 퀀트 알림 연결 완료. 오전 8:50 월세 퀀트, 오후 1시 개축 퀀트 새 물건을 보내드립니다.")
    elif "--test" in sys.argv:
        send_telegram("경매 퀀트 알림 연결 테스트입니다.")
    elif "--selftest" in sys.argv:
        for reg in REGION:
            print(reg, {r: max_bid(r, 9000, reg) for r in RENTS}, calc(10000, 70, 9400, reg))
    elif "--listen" in sys.argv:
        listen(int(sys.argv[sys.argv.index("--listen") + 1]))
    elif "--gaechuk" in sys.argv:
        g_run()
    elif "--gaechuk-full" in sys.argv:
        g_run(full=True)
    elif "--gaechuk-dry" in sys.argv:
        g_run(full=True, dry=True)
    elif "--full" in sys.argv:
        run(full=True)
    elif "--preview" in sys.argv:
        for m in fmt(screen(fetch_listings())): send_telegram(m)
    elif "--dry" in sys.argv:
        hits = screen(fetch_listings())
        for m in fmt(hits): print(m); print("-----")
    else:
        run()
