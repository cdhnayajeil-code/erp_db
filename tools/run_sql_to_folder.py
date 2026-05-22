# -*- coding: utf-8 -*-
"""
SQL 기반 프로젝트원가 폴더 생성 (READ-ONLY)

`doc\\sql_20260515_pjt_extract_full.sql` 의 4개 쿼리를 DB 에서 직접 실행하여
4종 CSV + _summary.json + 요약 HTML 을 별도 폴더(`<PJT_CD>_SQL/`) 에 생성한다.

사용:
    python _run_sql_to_folder.py 2024-056-SCH

Python 빌더(`_extract_pjt_folder.py`) 와 결과는 100% 동일해야 함.
불일치 발생 시 양쪽 동기화 필수.
"""
import csv
import json
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from html import escape
from collections import Counter

import pyodbc

if len(sys.argv) < 2:
    print("usage: python _run_sql_to_folder.py <PROJECT_NO>")
    sys.exit(1)

PJT_CD = sys.argv[1].strip()
BASE = Path(__file__).resolve().parent
# 출력 폴더 접미사 (두번째 인자, 기본 '' — v9.12 부터 SQL 빌더가 운영 표준).
# 빈 문자열이면 <PJT_CD>/ 직접 출력. 감사·검증용으로 '_SQL' 등 사용 가능.
SUFFIX = sys.argv[2] if len(sys.argv) >= 3 else ''
# 출력 베이스 경로 (세번째 인자, 기본 BASE)
OUT_BASE = Path(sys.argv[3]) if len(sys.argv) >= 4 else BASE
OUT_DIR = OUT_BASE / f"{PJT_CD}{SUFFIX}"
# SQL 파일 경로 — 환경변수 PMS_SQL_FILE 우선, 기본은 OneDrive 절대 경로
import os as _os
_sql_default = r"e:\OneDrive\1.JOB\ERP_DB\doc\sql_20260515_pjt_extract_full.sql"
SQL_FILE = Path(_os.environ.get("PMS_SQL_FILE", _sql_default))

sys.stdout.reconfigure(encoding="utf-8")
OUT_DIR.mkdir(exist_ok=True)

# ---------- DB 접속 ----------
info = {}
# 자격증명: .db 파일 우선, 없으면 환경변수 (GitHub Actions / cloud 환경 대응)
import os
_db_file = Path(r"e:\OneDrive\1.JOB\ERP_DB\.db")
if _db_file.exists():
    for line in _db_file.read_text(encoding="utf-8").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip().lower()] = v.strip()
else:
    _env = {
        "ip": os.environ.get("JEILMNS_HOST"),
        "id": os.environ.get("JEILMNS_USER"),
        "pw": os.environ.get("JEILMNS_PWD"),
    }
    missing = [k for k, v in _env.items() if not v]
    if missing:
        print(f"[FATAL] .db 파일 없음 + 환경변수 누락: {missing}")
        sys.exit(2)
    info = _env
conn = pyodbc.connect(
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={info['ip']};UID={info['id']};PWD={info['pw']};"
    f"TrustServerCertificate=yes;Connection Timeout=10;DATABASE=JEILMNS;"
)
cur = conn.cursor()


def ser(v):
    if isinstance(v, Decimal):
        return float(v) if v % 1 else int(v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return v


# ---------- 1. 프로젝트 마스터 ----------
print(f"\n=== [{PJT_CD}] 프로젝트 마스터 (보조 쿼리) ===")
cur.execute("""
SELECT P.PJT_CD, P.PJT_NM, P.PJT_STATUS,
       CONVERT(varchar(10), P.SO_DT, 120) AS SO_DT,
       P.BP_CD, B.BP_NM, P.PJT_TYPE
FROM PM_PROJECT_MASTER_KO174 P
LEFT JOIN B_BIZ_PARTNER B ON B.BP_CD = P.BP_CD
WHERE P.PJT_CD = ?
""", [PJT_CD])
rec = cur.fetchone()
if not rec:
    print(f"[ERROR] PJT_CD={PJT_CD} 미존재")
    sys.exit(2)
pjt = {
    'PJT_CD': rec[0], 'PJT_NM': rec[1], 'PJT_STATUS': rec[2],
    'SO_DT': rec[3], 'BP_CD': rec[4], 'BP_NM': rec[5], 'PJT_TYPE': rec[6],
}
print(f"  - {pjt['PJT_NM']}")
print(f"  - 거래처: {pjt['BP_NM']} / 수주: {pjt['SO_DT']}")


# ---------- 2. SQL 파일에서 Q1~Q4 추출 + 실행 ----------
print(f"\n=== SQL 4 쿼리 실행 ===")
sql_text = SQL_FILE.read_text(encoding='utf-8')
declare_stmt = f"DECLARE @PJT_CD nvarchar(50) = N'{PJT_CD}';"
parts = re.split(r'-- ={5,}\s*\n-- (Q\d+\..+?)\s*\n-- ={5,}', sql_text)
queries = {parts[i].split('.')[0].strip(): parts[i+1][:parts[i+1].find(';')+1]
           for i in range(1, len(parts), 2)}

results = {}  # 'Q1'..'Q4' → (cols, rows)
for label in ['Q1', 'Q2', 'Q3', 'Q4']:
    cur.execute(declare_stmt + '\n' + queries[label])
    cols = [d[0] for d in cur.description]
    rows = [[ser(v) for v in r] for r in cur.fetchall()]
    results[label] = (cols, rows)
    print(f"  {label}: {len(rows)} 행 / {len(cols)} 컬럼")


# ---------- 3. CSV 출력 (v2.0 양식 인식 컬럼만, 4종, 파일명에 PJT_CD prefix) ----------
print(f"\n=== CSV 출력 ===")
csv_names = {
    'Q1': f'{PJT_CD}_01_지출데이터.csv',
    'Q2': f'{PJT_CD}_02_수금데이터.csv',
    'Q3': f'{PJT_CD}_03_매입데이터.csv',
    'Q4': f'{PJT_CD}_04_수불데이터.csv',
}

# v9.12 — v2.0 양식 인식 13컬럼 + 추적 컬럼(자료유형/특이사항) 보존
# 사업관리팀이 자료유형 필터로 소모품매입 분리 가능하도록 자료유형/특이사항 항상 포함
PMS_COLS = {
    'Q1': ['계약번호','연도','회계일자','원가 투입 단계','사용항목1','사용항목2',
           '계정그룹','계정명','코드','거래처명','적요란','차변','미입고여부',
           '자료유형','특이사항'],
    'Q2': ['계약번호','회계일자','거래처명','적요란','수금액',
           '자료유형','특이사항'],
    'Q3': ['계약번호','연도','회계일자','원가 투입 단계','사용항목1','사용항목2',
           '계정그룹','계정명','코드','거래처명','적요란','차변','미입고여부',
           '자료유형','특이사항'],
    'Q4': ['계약번호','연도','회계일자','원가 투입 단계','사용항목1','사용항목2',
           '계정그룹','계정명','코드','거래처명','적요란','차변','미입고여부',
           '자료유형','특이사항'],
}

for label, fname in csv_names.items():
    cols, rows = results[label]
    pms_cols = PMS_COLS[label]
    col_idx = {c: i for i, c in enumerate(cols)}
    indices = [col_idx[c] for c in pms_cols if c in col_idx]
    out = OUT_DIR / fname
    with out.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow([cols[i] for i in indices])
        for r in rows:
            w.writerow(['' if r[i] is None else r[i] for i in indices])
    print(f"  {fname}: {len(rows)} 행 / {len(indices)} 컬럼")


# ---------- 4. _summary.json 생성 (CSV 컬럼 → 영문 키 매핑) ----------
print(f"\n=== _summary.json 생성 ===")

def row_to_dict(cols, row):
    return {c: row[i] for i, c in enumerate(cols)}

cost_cols, cost_rows_raw = results['Q1']
recv_cols, recv_rows_raw = results['Q2']
iv_cols,   iv_rows_raw   = results['Q3']
mv_cols,   mv_rows_raw   = results['Q4']

# 단순 매핑 함수
def parse_amt(v):
    try:
        return float(v) if v else 0
    except (TypeError, ValueError):
        return 0

cost_arr = []
for row in cost_rows_raw:
    r = row_to_dict(cost_cols, row)
    cost_arr.append({
        "proj": PJT_CD, "year": str(r.get('연도','')), "date": r.get('회계일자',''),
        "stage": r.get('원가 투입 단계',''),
        "item1": r.get('사용항목1',''),
        "item2": r.get('사용항목2',''),
        "acctGroup": r.get('계정그룹','') or '',
        "acctName": r.get('계정명','') or '',
        "code": r.get('코드','') or '',
        "vendor": r.get('거래처명','') or '',
        "note": r.get('적요란', r.get('적요','')) or '',
        "amount": parse_amt(r.get('차변')),
        "glNo": r.get('원인회계전표(GL_NO)','') or '',
        "refNo": r.get('증빙번호','') or '',
        "glPath": r.get('전표생성경로','') or '',
        "srcType": r.get('자료유형','') or '',
        "isPurDup": int(r.get('IS_PUR_DUP') or 0),
        "clue": r.get('특이사항','') or '',
    })

recv_arr = []
for row in recv_rows_raw:
    r = row_to_dict(recv_cols, row)
    recv_arr.append({
        "proj": PJT_CD, "date": r.get('회계일자',''),
        "vendor": r.get('거래처명','') or '',
        "note": r.get('적요란', r.get('적요','')) or '',
        "amount": parse_amt(r.get('수금액')),
        "glNo": r.get('원인회계전표(GL_NO)','') or '',
        "refNo": r.get('증빙번호','') or '',
        "glPath": r.get('전표생성경로','') or '',
        "srcType": r.get('자료유형','') or '',
        "clue": r.get('특이사항','') or '',
    })

iv_arr = []
for row in iv_rows_raw:
    r = row_to_dict(iv_cols, row)
    iv_arr.append({
        "proj": PJT_CD, "ivNo": r.get('IV번호',''),
        "ivDt": r.get('회계일자','') or r.get('매입일',''),
        "bpNm": r.get('거래처명','') or '',
        "itemCd": r.get('품목코드','') or '',
        "itemNm": r.get('품목명','') or '',
        "itemSpec": r.get('규격','') or '',
        "qty": parse_amt(r.get('수량')),
        "unit": r.get('단위','') or '',
        "prc": parse_amt(r.get('단가')),
        "locAmt": parse_amt(r.get('차변')),    # 차변 = 공급가 또는 GL차변금액
        "vatAmt": parse_amt(r.get('부가세')),
        "poNo": r.get('PO번호','') or '',
        "mvmtNo": r.get('수불번호(MVMT)','') or '',
        "tracking": r.get('트래킹번호', PJT_CD) or PJT_CD,
        "stage": r.get('원가 투입 단계','') or '',
        "item1": r.get('사용항목1','') or '',
        "item2": r.get('사용항목2','') or '',
        "acctGroup": r.get('계정그룹','') or '',
        "acctName": r.get('계정명','') or '',
        "code": r.get('코드','') or '',
        "note": r.get('적요란','') or '',
        "voucherNo": r.get('증빙(결의전표)','') or '',
        "glNo": r.get('원인회계전표(GL_NO)','') or '',
        "glPath": r.get('전표생성경로','') or '',
        "srcType": r.get('자료유형','') or '',
        "clue": r.get('특이사항','') or '',
    })

mv_arr = []
for row in mv_rows_raw:
    r = row_to_dict(mv_cols, row)
    mv_arr.append({
        "proj": PJT_CD, "date": r.get('회계일자',''),
        "stage": r.get('원가 투입 단계','') or r.get('단계','') or '',
        "item1": r.get('사용항목1','') or '',
        "item2": r.get('사용항목2','') or '',
        "acctGroup": r.get('계정그룹','') or '',
        "acctName": r.get('계정명','') or '',
        "code": r.get('코드','') or '',
        "itemCd": r.get('품목코드','') or '',
        "itemNm": r.get('품목명','') or r.get('거래처명','') or '',
        "itemSpec": r.get('규격','') or '',
        "vendor": r.get('거래처명','') or '',
        "note": r.get('적요란','') or '',
        "amount": parse_amt(r.get('차변')) or parse_amt(r.get('금액(원)')),
        "src": r.get('구분','') or 'MV',
        "refNo": r.get('증빙번호','') or '',
        "tracking": PJT_CD,
        "glNo": r.get('원인회계전표(GL_NO)','') or '',
        "glPath": r.get('전표생성경로','') or '',
        "srcType": r.get('자료유형','') or '',
        "clue": r.get('특이사항','') or '',
    })

# 합계 계산
cost_sum = sum(c['amount'] for c in cost_arr)
cost_dup_sum = sum(c['amount'] for c in cost_arr if c['isPurDup'] == 1)
cost_dup_cnt = sum(1 for c in cost_arr if c['isPurDup'] == 1)
recv_sum = sum(r['amount'] for r in recv_arr)
iv_sum = sum(i['locAmt'] for i in iv_arr)
iv_hdrs = len(set(i['ivNo'] for i in iv_arr))
mv_sum = sum(m['amount'] for m in mv_arr)
mv_hdrs = len(set(m['glNo'] for m in mv_arr))

summary = {
    "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "source": "SQL (doc/sql_20260515_pjt_extract_full.sql)",
    "projects": [{
        "pjtCd": PJT_CD,
        "pjtNm": pjt['PJT_NM'] or '',
        "bpNm": pjt['BP_NM'] or '',
        "soDt": pjt['SO_DT'] or '',
        "status": pjt['PJT_STATUS'] or '',
        "type": pjt['PJT_TYPE'] or '',
        "cost": {"lines": len(cost_arr), "amount": cost_sum,
                 "dupLines": cost_dup_cnt, "dupAmount": cost_dup_sum,
                 "netAmount": cost_sum - cost_dup_sum},
        "recv": {"lines": len(recv_arr), "amount": recv_sum},
        "iv": {"hdr": iv_hdrs, "lines": len(iv_arr), "amount": iv_sum, "vat": sum(i['vatAmt'] for i in iv_arr)},
        "mv": {"hdr": mv_hdrs, "lines": len(mv_arr), "amount": mv_sum},
    }],
    "cost": cost_arr,
    "receipts": recv_arr,
    "iv": iv_arr,
    "mv": mv_arr,
}

(OUT_DIR / "_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, separators=(',', ':')), encoding="utf-8"
)
print(f"  _summary.json 작성 (지출 {len(cost_arr)}/수금 {len(recv_arr)}/매입 {len(iv_arr)}/수불 {len(mv_arr)})")


# ---------- 5. 요약 HTML 생성 (빌더와 동일 디자인) ----------
print(f"\n=== 요약 HTML 생성 ===")

def fmt(n):
    return f"{int(n):,}" if n else "0"
def hesc(s):
    return escape(str(s or ""))

p = summary["projects"][0]

# GL_NO 묶음 카운트
gl_cnt_cost = Counter(r['glNo'] for r in cost_arr if r.get('glNo'))
gl_cnt_recv = Counter(r['glNo'] for r in recv_arr if r.get('glNo'))
gl_cnt_iv   = Counter(r['glNo'] for r in iv_arr if r.get('glNo'))
gl_cnt_mv   = Counter(r['glNo'] for r in mv_arr if r.get('glNo'))
gl_cnt_all  = Counter()
for c in (gl_cnt_cost, gl_cnt_recv, gl_cnt_iv, gl_cnt_mv):
    gl_cnt_all.update(c)

def gl_chip(gl_no, cnt_map):
    g = (gl_no or '').strip()
    if not g: return ''
    cnt = cnt_map.get(g, 1)
    if cnt > 1:
        return (f'<span title="{hesc(g)} (묶음 {cnt}건)">{hesc(g)}'
                f'<small style="color:#7c3aed;font-weight:700;margin-left:3px">×{cnt}</small></span>')
    return f'<span title="{hesc(g)}">{hesc(g)}</span>'

SRC_COLOR = {
    '매입':'#fef3c7;color:#92400e', '수불':'#cffafe;color:#155e75',
    '수기':'#e0e7ff;color:#3730a3', '매출':'#dcfce7;color:#166534',
    '세금계산서':'#ffe4e6;color:#9f1239', '정산':'#fce7f3;color:#9d174d',
    '환차':'#f3e8ff;color:#6b21a8', '카드/CA':'#fde68a;color:#854d0e',
}
TYPE_CHIP = {
    '지출':'#fee2e2;color:#991b1b',
    '수금':'#dcfce7;color:#166534', '매출정보':'#dcfce7;color:#166534',
    '매입':'#fef3c7;color:#92400e', '구매팀매입':'#fef3c7;color:#92400e',
    '수불':'#cffafe;color:#155e75', '물류팀출고':'#cffafe;color:#155e75',
}
def chip(label, palette):
    style = palette.get(label, '#f1f5f9;color:#475569')
    return f'<span style="background:{style};padding:1px 6px;border-radius:8px;font-size:10px;font-weight:700;white-space:nowrap">{hesc(label)}</span>'

# 지출 행
cost_html = ""
for r in cost_arr:
    dup_cls = ' style="background:#fee2e2"' if r.get("isPurDup") else ""
    grp_cnt = gl_cnt_cost.get(r['glNo'], 1) if r.get('glNo') else 1
    grp_cls = ' class="grp-row"' if grp_cnt > 1 else ''
    clue = r.get('clue','')
    cost_html += f"""<tr{dup_cls}{grp_cls}>
  <td class="mono dt">{hesc(r['date'])}</td>
  <td><span class="badge badge-stage">{hesc(r['stage'])}</span></td>
  <td class="trunc" title="{hesc(r['item1'])}">{hesc(r['item1'])}</td>
  <td class="mono cd">{hesc(r['code'])}</td>
  <td class="trunc" title="{hesc(r['acctName'])}">{hesc(r['acctName'])}</td>
  <td class="trunc" title="{hesc(r['vendor'])}">{hesc(r['vendor'])}</td>
  <td class="trunc note" title="{hesc(r['note'])}">{hesc(r['note'])}</td>
  <td class="num">{fmt(r['amount'])}</td>
  <td>{chip(r['srcType'], SRC_COLOR)}</td>
  <td class="mono path">{hesc(r['glPath'])}</td>
  <td class="mono ref" title="{hesc(r['refNo'])}">{hesc(r['refNo'])}</td>
  <td class="mono ref">{gl_chip(r['glNo'], gl_cnt_cost)}</td>
  <td class="mono clue" title="{hesc(clue)}">{hesc(clue)}</td>
</tr>"""

recv_html = ""
for r in recv_arr:
    grp_cnt = gl_cnt_recv.get(r['glNo'], 1) if r.get('glNo') else 1
    grp_cls = ' class="grp-row"' if grp_cnt > 1 else ''
    clue = r.get('clue','')
    recv_html += f"""<tr{grp_cls}>
  <td class="mono dt">{hesc(r['date'])}</td>
  <td class="trunc" title="{hesc(r['vendor'])}">{hesc(r['vendor'])}</td>
  <td class="trunc note" title="{hesc(r['note'])}">{hesc(r['note'])}</td>
  <td class="num">{fmt(r['amount'])}</td>
  <td>{chip(r['srcType'], SRC_COLOR)}</td>
  <td class="mono path">{hesc(r['glPath'])}</td>
  <td class="mono ref" title="{hesc(r['refNo'])}">{hesc(r['refNo'])}</td>
  <td class="mono ref">{gl_chip(r['glNo'], gl_cnt_recv)}</td>
  <td class="mono clue" title="{hesc(clue)}">{hesc(clue)}</td>
</tr>"""

iv_html = ""
for r in iv_arr:
    match_ok = (r['tracking'] or '').strip() == PJT_CD
    tr_cls = "" if match_ok else ' style="color:#b91c1c;font-weight:700"'
    grp_cnt = gl_cnt_iv.get(r['glNo'], 1) if r.get('glNo') else 1
    grp_cls = ' class="grp-row"' if grp_cnt > 1 else ''
    clue = r.get('clue','')
    note = r.get('note','')
    is_hdr_mode = '헤더모드' in clue
    row_style = ' style="background:#fef3c7"' if is_hdr_mode else ''
    iv_html += f"""<tr{grp_cls}{row_style}>
  <td class="mono dt">{hesc(r['ivDt'])}</td>
  <td class="mono ref" title="{hesc(r['ivNo'])}">{hesc(r['ivNo'])}</td>
  <td class="trunc" title="{hesc(r['bpNm'])}">{hesc(r['bpNm'])}</td>
  <td class="mono cd">{hesc(r['itemCd'])}</td>
  <td class="trunc" title="{hesc(r['itemNm'])}">{hesc(r['itemNm'])}</td>
  <td class="trunc note" title="{hesc(r['itemSpec'])}">{hesc(r['itemSpec'])}</td>
  <td class="trunc note" title="{hesc(note)}">{hesc(note)}</td>
  <td class="num">{r['qty']}</td>
  <td class="num">{fmt(r['locAmt'])}</td>
  <td>{chip(r['srcType'], SRC_COLOR)}</td>
  <td class="mono path">{hesc(r['glPath'])}</td>
  <td class="mono ref" title="{hesc(r['voucherNo'])}">{hesc(r['voucherNo'])}</td>
  <td class="mono ref">{gl_chip(r['glNo'], gl_cnt_iv)}</td>
  <td class="mono ref"{tr_cls} title="{hesc(r['tracking'])}">{hesc(r['tracking'])}</td>
  <td class="mono clue" title="{hesc(clue)}">{hesc(clue)}</td>
</tr>"""

mv_html = ""
for r in mv_arr:
    grp_cnt = gl_cnt_mv.get(r['glNo'], 1) if r.get('glNo') else 1
    grp_cls = ' class="grp-row"' if grp_cnt > 1 else ''
    clue = r.get('clue','')
    mv_html += f"""<tr{grp_cls}>
  <td class="mono dt">{hesc(r['date'])}</td>
  <td><span class="badge badge-{'src-iv' if r['src']=='IV' else 'src-mv'}">{r['src']}</span></td>
  <td><span class="badge badge-stage">{hesc(r['stage'])}</span></td>
  <td class="trunc" title="{hesc(r['acctName'])}">{hesc(r['acctName'])}</td>
  <td class="mono cd">{hesc(r['itemCd'])}</td>
  <td class="trunc note" title="{hesc(r['note'])}">{hesc(r['note'])}</td>
  <td class="num">{fmt(r['amount'])}</td>
  <td>{chip(r['srcType'], SRC_COLOR)}</td>
  <td class="mono path">{hesc(r['glPath'])}</td>
  <td class="mono ref" title="{hesc(r['refNo'])}">{hesc(r['refNo'])}</td>
  <td class="mono ref">{gl_chip(r['glNo'], gl_cnt_mv)}</td>
  <td class="mono clue" title="{hesc(clue)}">{hesc(clue)}</td>
</tr>"""

# 전체 탭
all_rows = []
for r in cost_arr:
    all_rows.append({"type":"지출","date":r['date'],"vendor":r['vendor'] or '',
                     "note":r['note'] or '',"amount":r['amount'],
                     "srcType":r['srcType'],"glPath":r['glPath'],
                     "refNo":r['refNo'],"glNo":r['glNo'],"clue":r.get('clue',''),
                     "isDup":r.get('isPurDup',0)})
for r in recv_arr:
    all_rows.append({"type":"매출정보","date":r['date'],"vendor":r['vendor'] or '',
                     "note":r['note'] or '',"amount":r['amount'],
                     "srcType":r['srcType'],"glPath":r['glPath'],
                     "refNo":r['refNo'],"glNo":r['glNo'],"clue":r.get('clue',''),"isDup":0})
for r in iv_arr:
    all_rows.append({"type":"구매팀매입","date":r['ivDt'],"vendor":r['bpNm'] or '',
                     "note":f"{r['itemNm'] or ''} {r['itemSpec'] or ''}".strip(),
                     "amount":r['locAmt'],
                     "srcType":r['srcType'],"glPath":r['glPath'],
                     "refNo":r['voucherNo'] or r['ivNo'],"glNo":r['glNo'],
                     "clue":r.get('clue',''),"isDup":0})
for r in mv_arr:
    all_rows.append({"type":"물류팀출고","date":r['date'],"vendor":r['itemNm'] or '',
                     "note":r['note'] or '',"amount":r['amount'],
                     "srcType":r['srcType'],"glPath":r['glPath'],
                     "refNo":r['refNo'],"glNo":r['glNo'],"clue":r.get('clue',''),"isDup":0})
all_rows.sort(key=lambda x: (x['date'] or '', x['type']))

all_html = ""
for r in all_rows:
    dup_cls = ' style="background:#fee2e2"' if r.get("isDup") else ""
    grp_cnt = gl_cnt_all.get(r['glNo'], 1) if r.get('glNo') else 1
    grp_cls = ' class="grp-row"' if grp_cnt > 1 else ''
    clue = r.get('clue','')
    all_html += f"""<tr{dup_cls}{grp_cls}>
  <td class="mono dt">{hesc(r['date'])}</td>
  <td>{chip(r['type'], TYPE_CHIP)}</td>
  <td class="trunc" title="{hesc(r['vendor'])}">{hesc(r['vendor'])}</td>
  <td class="trunc note" title="{hesc(r['note'])}">{hesc(r['note'])}</td>
  <td class="num">{fmt(r['amount'])}</td>
  <td>{chip(r['srcType'], SRC_COLOR)}</td>
  <td class="mono path">{hesc(r['glPath'])}</td>
  <td class="mono ref" title="{hesc(r['refNo'])}">{hesc(r['refNo'])}</td>
  <td class="mono ref">{gl_chip(r['glNo'], gl_cnt_all)}</td>
  <td class="mono clue" title="{hesc(clue)}">{hesc(clue)}</td>
</tr>"""

# 빌더와 동일 CSS/HTML 스켈레톤
html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>프로젝트 원가 요약 (ERP DB 추출) — {hesc(PJT_CD)}</title>
<style>
  :root {{ --primary:#1e40af; --accent:#0891b2; --bg:#f8fafc; --card:#fff;
          --border:#e2e8f0; --text:#1e293b; --mute:#64748b;
          --success:#16a34a; --warn:#d97706; --danger:#dc2626; }}
  * {{ box-sizing:border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{ font-family:'Pretendard','Malgun Gothic',sans-serif; background:var(--bg); color:var(--text); font-size:12px; line-height:1.45; }}
  .container {{ max-width:100%; margin:0 auto; padding:10px 14px; }}
  header.hero {{ background:linear-gradient(135deg, #6b21a8 0%, var(--accent) 100%);
                color:white; padding:12px 18px; border-radius:10px; margin-bottom:8px;
                box-shadow:0 4px 12px rgba(107,33,168,0.18); }}
  header.hero h1 {{ margin:0 0 4px 0; font-size:16px; font-weight:700; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  header.hero h1 .pjt-code {{ font-family:'JetBrains Mono','Consolas',monospace; font-size:14px; font-weight:800;
                              background:rgba(255,255,255,0.24); padding:3px 10px; border-radius:8px; letter-spacing:0.3px; }}
  header.hero .sub {{ font-size:11.5px; opacity:0.95; }}
  header.hero .meta {{ display:flex; gap:8px; margin-top:6px; font-size:10.5px; flex-wrap:wrap; }}
  header.hero .meta span {{ background:rgba(255,255,255,0.18); padding:2px 8px; border-radius:11px; }}
  header.hero .source-badge {{ background:rgba(255,255,255,0.28); padding:3px 10px; border-radius:11px; font-weight:700; }}
  .pjt-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:8px 14px; margin-bottom:8px; }}
  .pjt-stat-grid {{ display:grid; grid-template-columns:repeat(6, 1fr); gap:6px; }}
  .pjt-stat {{ padding:6px 9px; border-radius:6px; border:1px solid var(--border); background:#fafbfc; }}
  .pjt-stat .lbl {{ font-size:10px; color:var(--mute); font-weight:700; }}
  .pjt-stat .v {{ font-size:13.5px; font-weight:800; font-variant-numeric:tabular-nums; margin-top:2px; }}
  .pjt-stat .sub {{ font-size:9.5px; color:var(--mute); margin-top:1px; }}
  .pjt-stat.cost .v {{ color:#b91c1c; }} .pjt-stat.recv .v {{ color:#166534; }}
  .pjt-stat.iv .v {{ color:#92400e; }}   .pjt-stat.mv .v {{ color:#155e75; }}
  .pjt-stat.dup .v {{ color:#7f1d1d; }}  .pjt-stat.net .v {{ color:#0369a1; }}
  .search-bar {{ display:flex; gap:8px; align-items:center; background:var(--card); border:1px solid var(--border); border-radius:8px; padding:7px 10px; margin-bottom:6px; }}
  .search-bar input {{ flex:1; padding:6px 10px; border:1px solid var(--border); border-radius:6px; font-size:12px; }}
  .search-bar input:focus {{ outline:none; border-color:var(--primary); box-shadow:0 0 0 2px rgba(30,64,175,0.1); }}
  .search-bar .clear-btn {{ padding:4px 10px; background:#f1f5f9; border:1px solid var(--border); border-radius:5px; cursor:pointer; font-size:11px; color:var(--mute); }}
  .search-bar .clear-btn:hover {{ background:#e2e8f0; }}
  .search-bar .visible-count {{ font-size:10.5px; color:var(--primary); font-weight:700; min-width:80px; text-align:right; }}
  .tabs {{ display:flex; gap:3px; margin-bottom:6px; border-bottom:2px solid var(--border); }}
  .tab {{ padding:6px 14px; cursor:pointer; font-weight:600; color:var(--mute); border-bottom:3px solid transparent; margin-bottom:-2px; font-size:12.5px; }}
  .tab:hover {{ color:var(--primary); }}
  .tab.active {{ color:var(--primary); border-bottom-color:var(--primary); }}
  .tab .cnt {{ font-size:10px; background:#f1f5f9; padding:1px 6px; border-radius:8px; margin-left:4px; }}
  .tab.active .cnt {{ background:#dbeafe; color:var(--primary); }}
  .panel {{ display:none; }} .panel.active {{ display:block; }}
  .table-wrap {{ overflow:auto; max-height:calc(100vh - 280px); background:var(--card); border:1px solid var(--border); border-radius:6px; }}
  table.tbl {{ width:100%; border-collapse:collapse; font-size:10.5px; font-variant-numeric:tabular-nums; table-layout:fixed; }}
  table.tbl thead th {{ background:#1e293b; color:white; padding:5px 6px; text-align:left; font-size:10px; white-space:nowrap; position:sticky; top:0; z-index:2; border-right:1px solid #334155; }}
  table.tbl thead th.num {{ text-align:right; }}
  table.tbl tbody td {{ padding:3px 6px; border-bottom:1px solid #f1f5f9; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  table.tbl tbody td.num {{ text-align:right; }}
  table.tbl tbody td.muted {{ color:var(--mute); }}
  table.tbl tbody td.mono {{ font-family:'JetBrains Mono','Consolas',monospace; font-size:10px; }}
  table.tbl tbody td.cd {{ color:var(--primary); font-weight:700; }}
  table.tbl tbody td.dt {{ width:74px; }}
  table.tbl tbody td.ref {{ color:#475569; font-size:9.5px; }}
  table.tbl tbody td.path {{ color:#7c2d12; font-weight:700; font-size:10px; background:#fff7ed; }}
  table.tbl tbody td.clue {{ color:#155e75; font-size:9.5px; background:#ecfeff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  table.tbl tbody td.trunc {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  table.tbl tbody tr:nth-child(even) td {{ background:#fafbfc; }}
  table.tbl tbody tr:hover td {{ background:#fef9c3 !important; }}
  .badge {{ display:inline-block; padding:1px 5px; border-radius:8px; font-size:9.5px; font-weight:700; }}
  .badge-stage {{ background:#dbeafe; color:#1e3a8a; }}
  .badge-src-iv {{ background:#fef3c7; color:#92400e; }}
  .badge-src-mv {{ background:#cffafe; color:#155e75; }}
  table.tbl tbody tr.grp-row td:first-child {{ box-shadow:inset 3px 0 0 #a855f7; }}
</style>
</head>
<body>
<div class="container">
  <header class="hero">
    <h1><span class="pjt-code">{hesc(PJT_CD)}</span>프로젝트 원가 요약 <span class="source-badge">ERP DB 추출</span></h1>
    <div class="sub">{hesc(p['pjtNm'])}</div>
    <div class="meta">
      <span>생성 {summary['generatedAt']}</span>
      <span>출처 SQL: doc\\sql_20260515_pjt_extract_full.sql</span>
      <span>수주 {hesc(p['soDt'])}</span>
      <span>거래처 {hesc(p['bpNm'])}</span>
    </div>
  </header>

  <div class="pjt-card">
    <div class="pjt-stat-grid">
      <div class="pjt-stat cost"><div class="lbl">지출 (총)</div><div class="v">{fmt(p['cost']['amount'])}</div><div class="sub">{p['cost']['lines']} 행</div></div>
      <div class="pjt-stat dup"><div class="lbl">중복(매입·수불)</div><div class="v">{fmt(p['cost']['dupAmount'])}</div><div class="sub">{p['cost']['dupLines']} 행</div></div>
      <div class="pjt-stat net"><div class="lbl">순지출</div><div class="v">{fmt(p['cost']['netAmount'])}</div><div class="sub">합계−중복</div></div>
      <div class="pjt-stat recv"><div class="lbl">수금 (매출정보)</div><div class="v">{fmt(p['recv']['amount'])}</div><div class="sub">{p['recv']['lines']} 행</div></div>
      <div class="pjt-stat iv"><div class="lbl">매입 (구매팀매입)</div><div class="v">{fmt(p['iv']['amount'])}</div><div class="sub">HDR {p['iv']['hdr']} · 라인 {p['iv']['lines']}</div></div>
      <div class="pjt-stat mv"><div class="lbl">수불 (물류팀출고)</div><div class="v">{fmt(p['mv']['amount'])}</div><div class="sub">{p['mv']['lines']} 행</div></div>
    </div>
  </div>

  <div class="search-bar">
    <span style="font-size:14px">🔍</span>
    <input type="text" id="searchBox" placeholder="검색: 거래처, 적요, 품목, 계정, 증빙번호, GL_NO, 전표경로 등 (활성 탭에 적용)" oninput="applyFilter()">
    <button class="clear-btn" onclick="clearSearch()">지우기</button>
    <span class="visible-count" id="visibleCount"></span>
  </div>

  <div class="tabs">
    <div class="tab active" onclick="showTab(event,'all')">전체 <span class="cnt">{len(all_rows)}</span></div>
    <div class="tab" onclick="showTab(event,'cost')">지출 <span class="cnt">{p['cost']['lines']}</span></div>
    <div class="tab" onclick="showTab(event,'recv')">수금 (매출정보) <span class="cnt">{p['recv']['lines']}</span></div>
    <div class="tab" onclick="showTab(event,'iv')">매입 (구매팀매입) <span class="cnt">{p['iv']['lines']}</span></div>
    <div class="tab" onclick="showTab(event,'mv')">수불 (물류팀출고) <span class="cnt">{p['mv']['lines']}</span></div>
  </div>

  <div class="panel active" id="panel-all">
    <div class="table-wrap"><table class="tbl">
      <thead><tr>
        <th style="width:74px">일자</th><th style="width:54px">구분</th>
        <th style="width:160px">거래처/품목</th><th>적요</th>
        <th class="num" style="width:110px">금액</th>
        <th style="width:80px">자료유형</th><th style="width:50px">전표경로</th>
        <th style="width:120px">증빙번호</th><th style="width:120px">원인전표(GL_NO)</th>
        <th style="width:140px">특이사항</th>
      </tr></thead><tbody>{all_html}</tbody>
    </table></div>
  </div>

  <div class="panel" id="panel-cost">
    <div class="table-wrap"><table class="tbl">
      <thead><tr>
        <th style="width:74px">일자</th><th style="width:50px">단계</th>
        <th style="width:74px">사용항목1</th><th style="width:74px">계정코드</th>
        <th style="width:140px">계정명</th><th style="width:110px">거래처</th>
        <th>적요</th><th class="num" style="width:96px">차변</th>
        <th style="width:60px">자료유형</th><th style="width:50px">전표경로</th>
        <th style="width:104px">증빙번호</th><th style="width:120px">원인전표(GL_NO)</th>
        <th style="width:140px">특이사항</th>
      </tr></thead><tbody>{cost_html}</tbody>
    </table></div>
  </div>

  <div class="panel" id="panel-recv">
    <div class="table-wrap"><table class="tbl">
      <thead><tr>
        <th style="width:80px">일자</th><th style="width:160px">거래처</th>
        <th>적요</th><th class="num" style="width:120px">수금액</th>
        <th style="width:74px">자료유형</th><th style="width:50px">전표경로</th>
        <th style="width:120px">증빙번호</th><th style="width:130px">원인전표(GL_NO)</th>
        <th style="width:140px">특이사항</th>
      </tr></thead><tbody>{recv_html}</tbody>
    </table></div>
  </div>

  <div class="panel" id="panel-iv">
    <div class="table-wrap"><table class="tbl">
      <thead><tr>
        <th style="width:74px">매입일</th><th style="width:120px">IV번호</th>
        <th style="width:110px">거래처</th><th style="width:90px">품목코드</th>
        <th style="width:160px">품목명</th><th style="width:110px">규격</th>
        <th>적요</th>
        <th class="num" style="width:40px">수량</th><th class="num" style="width:90px">공급가</th>
        <th style="width:80px">자료유형</th><th style="width:46px">전표경로</th>
        <th style="width:110px">증빙(결의·TG)</th><th style="width:110px">원인전표(GL_NO)</th>
        <th style="width:110px">트래킹번호</th><th style="width:130px">특이사항</th>
      </tr></thead><tbody>{iv_html}</tbody>
    </table></div>
  </div>

  <div class="panel" id="panel-mv">
    <div class="table-wrap"><table class="tbl">
      <thead><tr>
        <th style="width:80px">일자</th><th style="width:46px">구분</th>
        <th style="width:54px">단계</th><th style="width:160px">계정명</th>
        <th style="width:120px">코드</th><th>적요란</th>
        <th class="num" style="width:104px">금액</th>
        <th style="width:74px">자료유형</th><th style="width:50px">전표경로</th>
        <th style="width:120px">증빙번호</th><th style="width:130px">원인전표(GL_NO)</th>
        <th style="width:140px">특이사항</th>
      </tr></thead><tbody>{mv_html}</tbody>
    </table></div>
  </div>
</div>

<script>
function showTab(ev, k) {{
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  ev.currentTarget.classList.add('active');
  document.getElementById('panel-'+k).classList.add('active');
  applyFilter();
}}
function applyFilter() {{
  const q = (document.getElementById('searchBox').value || '').trim().toLowerCase();
  const tbody = document.querySelector('.panel.active table.tbl tbody');
  if (!tbody) return;
  let visible = 0, total = 0;
  tbody.querySelectorAll('tr').forEach(tr => {{
    total++;
    if (!q || tr.textContent.toLowerCase().includes(q)) {{
      tr.style.display = ''; visible++;
    }} else {{ tr.style.display = 'none'; }}
  }});
  document.getElementById('visibleCount').textContent = q ? (visible + ' / ' + total + ' 건') : (total + ' 건');
}}
function clearSearch() {{
  document.getElementById('searchBox').value = ''; applyFilter();
}}
window.addEventListener('DOMContentLoaded', applyFilter);
</script>
</body>
</html>
"""

html_filename = f"프로젝트원가_요약_{PJT_CD}{SUFFIX}.html"
(OUT_DIR / html_filename).write_text(html_doc, encoding="utf-8")
print(f"  {html_filename} 작성")

cur.close()
conn.close()

print(f"\n=== 완료 (SQL 기반) : {OUT_DIR} ===")
print(f"  지출   : {len(cost_arr)} 행 / {cost_sum:,.0f} 원  (중복 {cost_dup_cnt}건/{cost_dup_sum:,.0f})")
print(f"  수금   : {len(recv_arr)} 행 / {recv_sum:,.0f} 원")
print(f"  매입   : {len(iv_arr)} 행 / {iv_sum:,.0f} 원")
print(f"  수불   : {len(mv_arr)} 행 / {mv_sum:,.0f} 원")
