# -*- coding: utf-8 -*-
"""blog_tools.py — 블로그 검수·블로그 통계 스킬 공용 스크립트
GitHub losermarxdr/sootax (main) 루트에 두고 스킬이 내려받아 쓴다.
사용법: version | audit | summary [연도] | month 목록 [연도] | years 목록 | totals | detail 목록 YYYY-MM
목록 = 세금 · 도서 · DVD · 강의노트 · 음반   (모든 통계는 게시일 기준, 음반은 아이튠즈 추가일)
"""
VERSION = '2026.10.02-1'
import json, re, time, html, subprocess, urllib.parse, collections, os

RAW = 'https://raw.githubusercontent.com/losermarxdr/sootax/main/'
SOOTAX = 'https://sootax.co.kr'
CHANGGO = 'https://changgo13.tistory.com'
UA = 'Mozilla/5.0'

TAX_FILES = [('structured-basic-list.json', '기초세금'),
             ('structured-tax-links.json', '분야별 세금'),
             ('structured-case-list.json', '예규와 판례')]
TAX_CATS = ['세무기장대행', '부동산 기초세금', '상속세와 증여세', '기업경영과 세금',
            '주제별 세금해설', '기업경영 관련 예규·판례', '부동산 관련 예규·판례']
DVD_GENRES = ['Rock_Pop', 'Jazz_Blues', 'Opera', 'Classical', 'Ballets', 'Theater']


def curl(url, tries=4, timeout=40):
    """본문 텍스트. sootax는 가끔 연결이 끊겨 재시도한다. 실패하면 ''"""
    for i in range(tries):
        r = subprocess.run(['curl', '-sL', '-A', UA, '--max-time', str(timeout), url],
                           capture_output=True)
        t = r.stdout.decode('utf-8', 'ignore')
        if r.returncode == 0 and len(t) > 200:
            return t
        time.sleep(2 + i * 2)
    return ''


def get_json(name):
    t = curl(RAW + name + '?nocache=' + str(int(time.time())))
    if not t:
        raise RuntimeError('GitHub JSON을 받지 못함: ' + name)
    return json.loads(t)


def load_all():
    """다섯 목록을 공통 모양 [{list, key, date, cat, title}]으로"""
    rows = []
    for f, grp in TAX_FILES:
        for c in get_json(f):
            for it in c['items']:
                rows.append(dict(list='세금', key=int(it['url'].rstrip('/').rsplit('/', 1)[1]),
                                 date=it.get('date', ''), cat=c['category'], group=grp,
                                 title=it['title']))
    for b in get_json('book_all_list.json'):
        rows.append(dict(list='도서', key=int(b['key']), date=str(b['DateAdded'])[:10],
                         cat=b['구분'], catno=int(b['구분NO']), title=f"{b['저자']}: {b['도서명']}"))
    for d in get_json('chaggo13_dvd_all_list.json'):
        rows.append(dict(list='DVD', key=int(d['key']), date=str(d['DateAdded'])[:10],
                         cat=d.get('Genre', ''), title=d.get('Title', ''), image=d.get('Image', '')))
    lec = get_json('lecture_catalog.json')
    for x in lec['items']:
        rows.append(dict(list='강의노트', key=int(x['key']), date=str(x['날짜'])[:10],
                         cat=x['구분'], title=x.get('강의명', '')))
    for a in get_json('json_allalbum.json'):
        rows.append(dict(list='음반', key=int(a['ID']), date=str(a['DateAdded'])[:10],
                         cat=a.get('장르', ''), title=f"{a['아티스트']} / {a['앨범']}",
                         image=a.get('앨범커버URL', '')))
    return rows, lec


def cat_order(rows, lst, lec=None):
    if lst == '세금':
        return TAX_CATS
    if lst == 'DVD':
        return DVD_GENRES
    if lst == '도서':
        seen = {}
        for r in rows:
            if r['list'] == '도서':
                seen[r['cat']] = r['catno']
        return [c for c, _ in sorted(seen.items(), key=lambda x: x[1])]
    if lst == '강의노트':
        return list(reversed(lec['gubun'])) if lec else sorted({r['cat'] for r in rows if r['list'] == '강의노트'})
    return None                                    # 음반: 나누지 않음


# ---------------- 블로그 카테고리 글 수 ----------------
def parse_cat_counts(page):
    """사이드바 카테고리 → [(이름, 글수)] (처음 나온 순서, 중복 제거)"""
    out, seen = [], set()
    for name, cnt in re.findall(r'>\s*([^<>]{1,60}?)\s*<span class="c_cnt">\((\d+)\)', page):
        name = html.unescape(name).strip()
        if name in seen:
            continue
        seen.add(name)
        out.append((name, int(cnt)))
    return out


def blog_counts():
    """{'sootax': {이름: 수}, 'changgo13': {이름: 수}} — sootax 첫 화면은 자주 끊겨서 글 페이지에서 읽는다"""
    res = {}
    for url in [SOOTAX + '/notice', SOOTAX + '/6430', SOOTAX + '/']:
        t = curl(url)
        c = parse_cat_counts(t)
        if c:
            res['sootax'] = dict(c)
            break
    t = curl(CHANGGO + '/')
    res['changgo13'] = dict(parse_cat_counts(t))
    return res


def rss_items():
    """sootax RSS 최근 글 [(key, 카테고리, 제목, 날짜)]"""
    t = curl(SOOTAX + '/rss')
    out = []
    for it in re.findall(r'<item>([\s\S]*?)</item>', t):
        g = lambda tag: (re.search(r'<' + tag + r'>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</' + tag + '>', it) or [None, ''])[1]
        link = g('link')
        m = re.search(r'/(\d+)/?$', link.strip())
        if m:
            out.append((int(m.group(1)), html.unescape(g('category')).strip(),
                        html.unescape(g('title')).strip(), g('pubDate')))
    return out


# ---------------- 표 ----------------
def md_table(header, rows):
    s = '| ' + ' | '.join(header) + ' |\n|' + '---|' * len(header) + '\n'
    for r in rows:
        s += '| ' + ' | '.join(str(x) for x in r) + ' |\n'
    return s


def cell(v):
    return str(v) if v else '·'


# ======================================================================
#  검수 (audit)
# ======================================================================
EXPECTED_LECTURE_EXCLUDED = 13     # 2026.09.28 기준 제외목록 행 수 (목차정리 12 + 모아보기 6825)
TAX_EXTRA = {'기업경영과 세금': (1, '분야별 세금 모아보기 6430')}   # 블로그에만 있고 목록에서 뺀 글


def audit():
    rows, lec = load_all()
    bc = blog_counts()
    so, cg = bc.get('sootax', {}), bc.get('changgo13', {})
    by = collections.defaultdict(list)
    for r in rows:
        by[r['list']].append(r)
    out, bad = [], []

    def line(name, blog, expect_note, json_n, ok, note=''):
        out.append([name, blog, expect_note, json_n, '✓' if ok else '✗ 불일치', note])
        if not ok:
            bad.append(name)

    # --- 세금 ---
    if not so:
        out.append(['sootax 카테고리', '읽기 실패', '', '', '✗', '블로그 접속 확인 필요'])
        bad.append('sootax 접속')
    else:
        tcnt = collections.Counter(r['cat'] for r in by['세금'])
        for c in TAX_CATS:
            b = so.get(c)
            extra, why = TAX_EXTRA.get(c, (0, ''))
            if b is None:
                line('세금 · ' + c, '없음', '', tcnt[c], False, '블로그 카테고리 이름 확인')
                continue
            line('세금 · ' + c, b, (f'−{extra} ({why})' if extra else ''), tcnt[c], b - extra == tcnt[c])
        # --- 도서: 「책 YYYY-YY」 하위 카테고리 ↔ DateAdded 연도 ---
        ranges = []
        for name, n in so.items():
            m = re.match(r'^책\s*(\d{4})-(\d{2,4})$', name)
            if m:
                a = int(m.group(1)); e = m.group(2); e = int(e) if len(e) == 4 else int(m.group(1)[:2] + e)
                ranges.append((a, e, name, n))
        ranges.sort()
        years = collections.Counter(int(r['date'][:4]) for r in by['도서'] if r['date'][:4].isdigit())
        for i, (a, e, name, n) in enumerate(ranges):
            lo = -1 if i == 0 else a                      # 가장 오래된 구간은 그 이전 해까지 포함
            j = sum(v for y, v in years.items() if lo <= y <= e) if lo >= 0 else sum(v for y, v in years.items() if y <= e)
            line('도서 · ' + name, n, f'DateAdded {a if i else "~"}–{e}', j, n == j)
        # 2026.10.02 카테고리 정리: 책 2023-26 + 책 2012-22 → 「읽은 책」, 연도별 책 밑줄긋기 → 「연도별 정리」
        rb = so.get('읽은 책')
        if rb is not None:
            line('도서 · 읽은 책', rb, '', len(by['도서']), rb == len(by['도서']))
        ybn = '연도별 정리' if '연도별 정리' in so else '연도별 책 밑줄긋기'
        yb = so.get(ybn)
        tb = so.get('책 밑줄긋기')
        if tb is not None:
            line('도서 · 책 밑줄긋기 합계', tb, f'−{ybn} {yb}', len(by['도서']), tb - (yb or 0) == len(by['도서']))
        # --- 강의노트 ---
        lb = so.get('강의노트')
        if lb is not None:
            diff = lb - len(by['강의노트'])
            line('강의노트', lb, f'−제외목록 (기준 {EXPECTED_LECTURE_EXCLUDED})', len(by['강의노트']),
                 diff == EXPECTED_LECTURE_EXCLUDED,
                 '' if diff == EXPECTED_LECTURE_EXCLUDED else f'차이 {diff} — 제외목록 행 수가 {diff}이면 정상(새 목차정리·모아보기 글)')
    # --- DVD ---
    if not cg:
        out.append(['changgo13 카테고리', '읽기 실패', '', '', '✗', '블로그 접속 확인 필요'])
        bad.append('changgo13 접속')
    else:
        tot = cg.get('개별 Blu-ray 구매목록', cg.get('분류 전체보기'))
        line('DVD · 개별 Blu-ray 구매목록', tot, '', len(by['DVD']), tot == len(by['DVD']))
        if cg.get('Temp'):
            line('DVD · Temp', cg['Temp'], '0이어야 함', 0, False, 'Temp 카테고리에 글이 있음')

    # --- 내부 점검 ---
    notes = []
    for lst in ['세금', '도서', 'DVD', '강의노트', '음반']:
        ks = collections.Counter(r['key'] for r in by[lst])
        dup = sorted(k for k, v in ks.items() if v > 1)
        if dup:
            notes.append(f'✗ {lst}: key(ID) 중복 {dup}')
    nd = [r['key'] for r in by['세금'] if not re.match(r'^\d{4}-\d{2}-\d{2}$', r['date'] or '')]
    if nd:
        notes.append(f'✗ 세금: 게시일 없음 {nd} → [세금목록 관리] > [게시일 채우기]')
    unc = sorted(r['key'] for r in by['도서'] if r['cat'] == '미분류')
    notes.append(f'ℹ 도서: 미분류 {len(unc)}권' + (f' {unc}' if unc else '') + (' → 미분류 검수 대상' if unc else ''))
    ng = [r['key'] for r in by['DVD'] if r['cat'] not in DVD_GENRES]
    if ng:
        notes.append(f'✗ DVD: 장르 없음/이상 {ng}')
    ni = [r['key'] for r in by['DVD'] if not r.get('image')]
    if ni:
        notes.append(f'✗ DVD: 이미지 없음 {ni}')
    # DVD 카탈로그 ↔ 원본
    cls = {int(x['key']) for x in get_json('dvd_catalog.json')}
    pop = {int(x['key']) for x in get_json('dvd_catalog_pop.json')}
    want_c = {r['key'] for r in by['DVD'] if r['cat'] in ('Opera', 'Classical', 'Ballets')}
    want_p = {r['key'] for r in by['DVD'] if r['cat'] in ('Rock_Pop', 'Jazz_Blues')}
    for nm, have, want, how in [('클래식 카탈로그', cls, want_c, '[DVD목록 관리] ① → ②'),
                                ('대중음악 카탈로그', pop, want_p, '[대중음악 카탈로그] ① → ②')]:
        miss, extra = sorted(want - have), sorted(have - want)
        if miss or extra:
            notes.append(f'✗ DVD {nm}: 빠진 key {miss} / 원본에 없거나 장르가 다른 key {extra} → {how}')
        else:
            notes.append(f'✓ DVD {nm}: {len(have)}건, 원본 해당 장르와 일치')
    # 음반
    al = by['음반']
    pair = collections.Counter(r['title'] for r in al)
    dpair = [t for t, v in pair.items() if v > 1]
    if dpair:
        notes.append(f'✗ 음반: 같은 아티스트/앨범 중복 {dpair[:10]}')
    nc = [r['key'] for r in al if not r.get('image')]
    if nc:
        notes.append(f'✗ 음반: 커버 URL 없음 ID {nc[:20]}')
    tmp = collections.Counter(r['cat'] for r in al if re.match(r'^B \d{4}', r['cat']))
    notes.append(f'ℹ 음반: {len(al)}건 · 임시 장르 {sum(tmp.values())}건 ' + (str(dict(tmp)) if tmp else ''))
    # RSS 최근 글 중 목록에 없는 글
    have = {(r['list'], r['key']) for r in rows}
    late = []
    for k, cat, title, pub in rss_items():
        head = cat.split('/')[0]
        lst = {'기초세금': '세금', '분야별세금': '세금', '책 밑줄긋기': '도서', '강의노트': '강의노트'}.get(head)
        if not lst or (lst, k) in have:
            continue
        why = ''
        if '월별세무일정안내' in cat or '연도별 책 밑줄긋기' in cat or '연도별 정리' in cat or '모아보기' in title:
            why = '(제외 대상 — 정상)'
        elif '목차' in title and lst == '강의노트':
            why = '(목차정리 — 제외목록에 있으면 정상)'
        late.append(f'{k} [{cat}] {title} {why}')
    if late:
        notes.append('ℹ RSS 최근 글 중 목록 JSON에 없는 글 (올린 지 30분~1시간 안이면 아직 반영 전):\n    ' + '\n    '.join(late))
    return out, notes, bad


def print_audit():
    out, notes, bad = audit()
    print('## 블로그 검수 결과\n')
    print(md_table(['항목', '블로그', '빼는 글·기준', '목록(JSON)', '결과', '비고'], out))
    print('### 내부 점검\n')
    for n in notes:
        print('- ' + n)
    print('\n**종합:** ' + ('모두 정상' if not bad else '확인 필요 → ' + ', '.join(bad)))


# ======================================================================
#  통계 (stats)
# ======================================================================
LISTS = ['세금', '도서', 'DVD', '강의노트', '음반']


def month_table(rows, lec, lst, year, today):
    """목록 하나: 행=카테고리(고정 순서), 열=1~12월+계. ·=0건, 빈칸=아직 안 온 달"""
    sub = [r for r in rows if r['list'] == lst and r['date'][:4] == year]
    last = 12 if year < today[:4] else (int(today[5:7]) if year == today[:4] else 0)
    order = cat_order(rows, lst, lec)
    cnt = collections.Counter(((r['cat'] if order else lst), int(r['date'][5:7])) for r in sub)
    keys = order if order else [lst]
    body, colsum = [], [0] * 12
    for c in keys:
        cells, s = [], 0
        for m in range(1, 13):
            v = cnt[(c, m)]; s += v; colsum[m - 1] += v
            cells.append('' if m > last else cell(v))
        body.append([c] + cells + [cell(s)])
    if order:
        body.append(['**계**'] + [('' if m > last else (f'**{colsum[m-1]}**' if colsum[m-1] else '·')) for m in range(1, 13)] + [f'**{sum(colsum)}**'])
    return md_table(['카테고리' if order else '', *[f'{m}월' for m in range(1, 13)], '계'], body)


def summary_table(rows, year, today):
    """다섯 목록: 행=목록, 열=1~12월+계"""
    last = 12 if year < today[:4] else (int(today[5:7]) if year == today[:4] else 0)
    cnt = collections.Counter((r['list'], int(r['date'][5:7])) for r in rows if r['date'][:4] == year)
    body, colsum = [], [0] * 12
    for l in LISTS:
        cells, s = [], 0
        for m in range(1, 13):
            v = cnt[(l, m)]; s += v; colsum[m - 1] += v
            cells.append('' if m > last else cell(v))
        body.append([l] + cells + [cell(s)])
    body.append(['**계**'] + [('' if m > last else (f'**{colsum[m-1]}**' if colsum[m-1] else '·')) for m in range(1, 13)] + [f'**{sum(colsum)}**'])
    return md_table(['목록', *[f'{m}월' for m in range(1, 13)], '계'], body)


def year_table(rows, lec, lst):
    """목록 하나: 행=카테고리, 열=연도+계"""
    sub = [r for r in rows if r['list'] == lst]
    order = cat_order(rows, lst, lec) or [lst]
    ys = sorted({r['date'][:4] for r in sub})
    cnt = collections.Counter(((r['cat'] if len(order) > 1 or order[0] != lst else lst), r['date'][:4]) for r in sub)
    body = [[c] + [cell(cnt[(c, y)]) for y in ys] + [sum(cnt[(c, y)] for y in ys)] for c in order]
    if len(order) > 1:
        body.append(['**계**'] + [f'**{sum(cnt[(c, y)] for c in order)}**' for y in ys] + [f'**{len(sub)}**'])
    return md_table(['카테고리', *ys, '계'], body)


def totals_table(rows):
    """다섯 목록: 행=연도, 열=목록+계"""
    cnt = collections.Counter((r['list'], r['date'][:4]) for r in rows)
    ys = sorted({y for _, y in cnt})
    body = [[y] + [cell(cnt[(l, y)]) for l in LISTS] + [sum(cnt[(l, y)] for l in LISTS)] for y in ys]
    body.append(['**계**'] + [f'**{sum(cnt[(l, y)] for y in ys)}**' for l in LISTS] + [f'**{len(rows)}**'])
    return md_table(['연도', *LISTS, '계'], body)


def detail(rows, lst, ym):
    sub = sorted([r for r in rows if r['list'] == lst and r['date'][:7] == ym], key=lambda r: (r['date'], r['key']))
    head = ['날짜', 'key' if lst != '음반' else 'ID', '카테고리', '제목']
    body = [[r['date'], r['key'], r['cat'], r['title']] for r in sub]
    return f'**{lst} {ym} — {len(sub)}건**\n\n' + (md_table(head, body) if body else '_없음_\n')


GUIDE = """더 자세히 보려면 이렇게 요청하세요.
- 「세금 월별」「DVD 월별」 … 목록 하나를 카테고리(DVD는 장르)별로 나눈 월별 표 (「2025년 도서 월별」처럼 연도 지정 가능)
- 「연도별」 … 다섯 목록의 연도별 합계
- 「세금 연도별」「DVD 연도별」 … 목록 하나를 카테고리(장르) × 연도로
- 「9월에 추가된 책」「2026년 8월 DVD」 … 그 달에 추가된 글 목록"""


def main():
    import sys, datetime
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime('%Y-%m-%d')
    a = sys.argv[1:] or ['summary']
    if a[0] == 'version':
        print(VERSION); return
    if a[0] == 'audit':
        print_audit(); return
    rows, lec = load_all()
    if a[0] == 'summary':                       # summary [연도]
        y = a[1] if len(a) > 1 else today[:4]
        print(f'## 블로그 통계 — {y}년 월별 ({today} 기준)\n')
        print(summary_table(rows, y, today))
        print('\n' + GUIDE)
    elif a[0] == 'month':                       # month 목록 [연도]
        y = a[2] if len(a) > 2 else today[:4]
        print(f'### {a[1]} — {y}년 월별\n')
        print(month_table(rows, lec, a[1], y, today))
    elif a[0] == 'years':                       # years 목록
        print(f'### {a[1]} — 연도별\n')
        print(year_table(rows, lec, a[1]))
    elif a[0] == 'totals':
        print('### 연도별 합계 (음반은 아이튠즈 추가일)\n')
        print(totals_table(rows))
    elif a[0] == 'detail':                      # detail 목록 YYYY-MM
        print(detail(rows, a[1], a[2]))
    else:
        print('사용법: version | audit | summary [연도] | month 목록 [연도] | years 목록 | totals | detail 목록 YYYY-MM')


if __name__ == '__main__':
    main()
