-- =====================================================================
-- 사업관리 프로젝트원가 — 4종 데이터 추출 SQL (단일 파일, v9)
-- =====================================================================
-- 작성: 2026-05-15 (v9)
-- 표준 명세: 사업관리\프로젝트원가 자료\_README_데이터파이프라인.md
--
-- v9 변경 사항:
--   1) IS_PUR_DUP 행은 지출에서 결과 자체 제외 (WHERE 절 NOT IN AP/IM)
--   2) 매입 — IV 라인합계=0 인 경우 IV 헤더 1행 + 첫품목 외 N건 + GL 차변금액 사용
--      + 매입 데이터에 [적요] 컬럼 신규 추가
--   3) 수불 — AP 분개 제거, IM 중 OI 시작만 (I_GOODS_MOVEMENT_HEADER 사용)
--      + 자료유형 = MOV_TYPE 한글명 매핑 (잠정 사전)
--   4) 거래처 보강 fallback — NAME 없으면 INSRT_USER_ID 의 username (이메일 @ 앞부분) 사용
--
-- 잠정 매핑 (사용자 정정 대기):
--   MOV_TYPE I03 → 생산출고(제작)
--   MOV_TYPE I04 → 생산출고(설치)
--   기타 코드는 코드 원형 유지
--
-- ※ READ-ONLY (SELECT only)
-- =====================================================================

DECLARE @PJT_CD nvarchar(50) = N'2024-056-SCH';

-- =====================================================================
-- Q1. 지출데이터 (IS_PUR_DUP=1 제외, 매입·수불 분개 GL 제거)
-- =====================================================================
WITH
  item_map AS (
    SELECT N'41000101' AS ACCT_CD, N'제작'  AS STAGE, N'원재료'      AS ITEM1, N'원재료' AS ITEM2
    UNION ALL SELECT N'41000102', N'제작',  N'부재료',      N'부재료'
    UNION ALL SELECT N'43000501', N'제작',  N'직접 인건비', N'복리후생비(식대)'
    UNION ALL SELECT N'43001101', N'제작',  N'간접인건비',  N'여비교통비(국내)'
    UNION ALL SELECT N'43001103', N'제작',  N'간접인건비',  N'제)여비교통비(해외)'
    UNION ALL SELECT N'43001901', N'제작',  N'제경비',      N'운반비(자재)'
    UNION ALL SELECT N'43002503', N'제작',  N'소모품비',    N'소모품비(자재/기타)'
    UNION ALL SELECT N'43003311', N'제작',  N'외주용역비',  N'생산 도급 외주 용역비'
    UNION ALL SELECT N'43003701', N'제작',  N'외주가공비',  N'외주가공비'
    UNION ALL SELECT N'43003901', N'수출운송', N'포장비',   N'포장비'
    UNION ALL SELECT N'46003701', N'설치',  N'외주 용역비', N'설치공사(배관/전기/도비)'
    UNION ALL SELECT N'53012502', N'판관',  N'운송비',      N'판)운반비(운임비)'
  )
SELECT
  @PJT_CD                                          AS [계약번호],
  YEAR(I.GL_DT)                                    AS [연도],
  CONVERT(varchar(10), I.GL_DT, 120)               AS [회계일자],
  COALESCE(IM.STAGE,
    CASE
      WHEN I.ACCT_CD LIKE '41%' THEN N'제작'
      WHEN I.ACCT_CD LIKE '46%' OR AC.ACCT_NM LIKE N'설치%' THEN N'설치'
      WHEN I.ACCT_CD LIKE '43%' OR AC.ACCT_NM LIKE N'제)%' THEN N'제작'
      WHEN I.ACCT_CD LIKE '53%' OR AC.ACCT_NM LIKE N'판)%' THEN N'판관'
      WHEN I.ACCT_CD LIKE '52%' THEN N'판관'
      WHEN I.ACCT_CD LIKE '44%' THEN N'수출운송'
      ELSE N''
    END)                                           AS [원가 투입 단계],
  COALESCE(IM.ITEM1,
    CASE
      WHEN AC.ACCT_NM LIKE N'%원재료%' THEN N'원재료'
      WHEN AC.ACCT_NM LIKE N'%부재료%' THEN N'부재료'
      WHEN AC.ACCT_NM LIKE N'%외주가공%' THEN N'외주가공비'
      WHEN AC.ACCT_NM LIKE N'%지급수수료%' AND AC.ACCT_NM LIKE N'%용역%' THEN N'외주용역비'
      WHEN AC.ACCT_NM LIKE N'%여비%' OR AC.ACCT_NM LIKE N'%교통%' THEN N'간접인건비'
      WHEN AC.ACCT_NM LIKE N'%복리%' OR AC.ACCT_NM LIKE N'%식대%' THEN N'직접 인건비'
      WHEN AC.ACCT_NM LIKE N'%운반%' OR AC.ACCT_NM LIKE N'%운임%' OR AC.ACCT_NM LIKE N'%운송%'
        THEN CASE WHEN I.ACCT_CD LIKE '53%' OR AC.ACCT_NM LIKE N'판)%' THEN N'운송비' ELSE N'제경비' END
      WHEN AC.ACCT_NM LIKE N'%소모품%' THEN N'소모품비'
      WHEN AC.ACCT_NM LIKE N'%포장%' THEN N'포장비'
      WHEN AC.ACCT_NM LIKE N'%설치%' OR I.ACCT_CD LIKE '46%' THEN N'외주 용역비'
      ELSE N'기타'
    END)                                           AS [사용항목1],
  COALESCE(IM.ITEM2,
    CASE
      WHEN LEFT(AC.ACCT_NM, 2) = N'제)'   THEN SUBSTRING(AC.ACCT_NM, 3, 200)
      WHEN LEFT(AC.ACCT_NM, 3) = N'설치)' THEN SUBSTRING(AC.ACCT_NM, 4, 200)
      WHEN LEFT(AC.ACCT_NM, 2) = N'판)'   THEN SUBSTRING(AC.ACCT_NM, 3, 200)
      ELSE COALESCE(AC.ACCT_NM, N'')
    END)                                           AS [사용항목2],
  AC.GP_CD                                         AS [계정그룹],
  AC.ACCT_NM                                       AS [계정명],
  I.ACCT_CD                                        AS [코드],
  -- 거래처 보강: BP_NM → Z_USR_MAST_REC.USR_NM (ERP 사용자 마스터, 예: "공정설계팀_진보선(퇴사)") → username
  COALESCE(
    NULLIF(LTRIM(RTRIM(B.BP_NM)), ''),
    NULLIF(LTRIM(RTRIM(U.USR_NM)), ''),
    CASE WHEN H.INSRT_USER_ID IS NOT NULL AND H.INSRT_USER_ID <> ''
         THEN LEFT(H.INSRT_USER_ID,
                   CASE WHEN CHARINDEX('@', H.INSRT_USER_ID) > 0
                        THEN CHARINDEX('@', H.INSRT_USER_ID) - 1
                        ELSE LEN(H.INSRT_USER_ID) END)
         ELSE N'' END,
    N''
  )                                                AS [거래처명],
  -- 적요: 헤더/라인 결합 (매입 IV 결합은 더 이상 적용 안 함 — 매입에 귀속)
  CASE
    WHEN (H.GL_DESC IS NULL OR LTRIM(RTRIM(H.GL_DESC)) = '')
      THEN COALESCE(LTRIM(RTRIM(I.ITEM_DESC)), '')
    WHEN (I.ITEM_DESC IS NULL OR LTRIM(RTRIM(I.ITEM_DESC)) = '')
      THEN LTRIM(RTRIM(H.GL_DESC))
    WHEN LTRIM(RTRIM(H.GL_DESC)) = LTRIM(RTRIM(I.ITEM_DESC))
      THEN LTRIM(RTRIM(I.ITEM_DESC))
    ELSE LTRIM(RTRIM(H.GL_DESC)) + N' / ' + LTRIM(RTRIM(I.ITEM_DESC))
  END                                              AS [적요란],
  CAST(I.ITEM_LOC_AMT AS bigint)                   AS [차변],
  N''                                              AS [미입고여부],
  CASE H.GL_INPUT_TYPE
    WHEN 'TG' THEN N'수기' WHEN 'AR' THEN N'매출' WHEN 'UX' THEN N'환차'
    WHEN 'IF' THEN N'정산' WHEN 'BN' THEN N'세금계산서' WHEN 'CA' THEN N'카드/CA'
    ELSE H.GL_INPUT_TYPE END                       AS [자료유형],
  H.GL_INPUT_TYPE                                  AS [전표생성경로],
  COALESCE(NULLIF(LTRIM(RTRIM(H.REF_NO)), ''), N'') AS [증빙번호],
  I.GL_NO                                          AS [원인회계전표(GL_NO)],
  0                                                AS [IS_PUR_DUP],
  N''                                              AS [특이사항]
FROM A_GL_ITEM I
JOIN A_GL H               ON H.GL_NO    = I.GL_NO
LEFT JOIN A_ACCT AC       ON AC.ACCT_CD = I.ACCT_CD
LEFT JOIN A_ACCT_GP GP    ON GP.GP_CD   = AC.GP_CD
LEFT JOIN B_BIZ_PARTNER B ON B.BP_CD    = I.BP_CD
LEFT JOIN Z_USR_MAST_REC U ON U.USR_ID = H.INSRT_USER_ID
LEFT JOIN item_map IM ON IM.ACCT_CD = I.ACCT_CD
WHERE I.PROJECT_NO = @PJT_CD
  AND I.DR_CR_FG = 'DR'
  AND (I.ACCT_CD LIKE '4%' OR I.ACCT_CD LIKE '52%' OR I.ACCT_CD LIKE '53%')
  -- ★ v9 신규: 매입(AP)·수불(IM) 분개 GL 은 매입/수불 탭에서 처리하므로 지출에서 제외
  AND H.GL_INPUT_TYPE NOT IN ('AP', 'IM')
  -- ★ v9.2 신규: 원인전표(GL_NO) 없는 행 제외
  AND I.GL_NO IS NOT NULL AND I.GL_NO <> ''
ORDER BY I.GL_DT, I.GL_NO, I.ITEM_SEQ;


-- =====================================================================
-- Q2. 수금데이터 (변경 없음)
-- =====================================================================
SELECT
  @PJT_CD                                          AS [계약번호],
  CONVERT(varchar(10), I.GL_DT, 120)               AS [회계일자],
  COALESCE(B.BP_NM, N'')                           AS [거래처명],
  CASE
    WHEN (H.GL_DESC IS NULL OR LTRIM(RTRIM(H.GL_DESC)) = '')
      THEN COALESCE(LTRIM(RTRIM(I.ITEM_DESC)), '')
    WHEN (I.ITEM_DESC IS NULL OR LTRIM(RTRIM(I.ITEM_DESC)) = '')
      THEN LTRIM(RTRIM(H.GL_DESC))
    WHEN LTRIM(RTRIM(H.GL_DESC)) = LTRIM(RTRIM(I.ITEM_DESC))
      THEN LTRIM(RTRIM(I.ITEM_DESC))
    ELSE LTRIM(RTRIM(H.GL_DESC)) + N' / ' + LTRIM(RTRIM(I.ITEM_DESC))
  END                                              AS [적요란],
  CAST(I.ITEM_LOC_AMT AS bigint)                   AS [수금액],
  -- 자료유형: 전표경로 기반 (수기/매출/세금계산서 등). HTML 탭 헤더에서 "매출정보" 분류명 표시.
  CASE H.GL_INPUT_TYPE
    WHEN 'AP' THEN N'매입' WHEN 'IM' THEN N'수불' WHEN 'TG' THEN N'수기'
    WHEN 'AR' THEN N'매출' WHEN 'UX' THEN N'환차' WHEN 'IF' THEN N'정산'
    WHEN 'BN' THEN N'세금계산서' WHEN 'CA' THEN N'카드/CA'
    ELSE H.GL_INPUT_TYPE END                       AS [자료유형],
  H.GL_INPUT_TYPE                                  AS [전표생성경로],
  COALESCE(NULLIF(LTRIM(RTRIM(H.REF_NO)), ''), N'') AS [증빙번호],
  I.GL_NO                                          AS [원인회계전표(GL_NO)],
  N''                                              AS [특이사항]
FROM A_GL_ITEM I
JOIN A_GL H ON H.GL_NO = I.GL_NO
LEFT JOIN A_ACCT AC ON AC.ACCT_CD = I.ACCT_CD
LEFT JOIN B_BIZ_PARTNER B ON B.BP_CD = I.BP_CD
WHERE I.PROJECT_NO = @PJT_CD
  AND I.DR_CR_FG = 'CR'
  AND I.ACCT_CD LIKE '51%'
  AND I.GL_NO IS NOT NULL AND I.GL_NO <> ''            -- v9.2: 원인전표 없는 행 제외
ORDER BY I.GL_DT, I.GL_NO;


-- =====================================================================
-- Q3. 매입데이터 (v9.9 — 양식 인식 13컬럼 + 매입 매핑 사전, _매입_사용항목_매핑사전.csv 동기화)
-- =====================================================================
WITH
  iv_grouped AS (
    SELECT
      IVD.IV_NO, IVD.IV_SEQ_NO,
      CONVERT(varchar(10), IVH.IV_DT, 120) AS IV_DT,
      IVH.BP_CD, B.BP_NM, IVH.IV_TYPE_CD, IVT.IV_TYPE_NM,
      IVH.GL_NO AS VOUCHER_NO,
      IVD.ITEM_CD, BI.ITEM_NM, BI.SPEC,
      LEFT(COALESCE(IVD.ITEM_CD,''), 1) AS FC,
      IVD.IV_QTY, IVD.IV_UNIT, IVD.IV_PRC,
      IVD.IV_LOC_AMT, IVD.VAT_LOC_AMT,
      IVD.PO_NO, IVD.PO_SEQ_NO, IVD.MVMT_NO, IVD.TRACKING_NO,
      ROW_NUMBER() OVER (PARTITION BY IVD.IV_NO ORDER BY IVD.IV_SEQ_NO) AS rn,
      COUNT(*)     OVER (PARTITION BY IVD.IV_NO) AS line_cnt,
      SUM(COALESCE(IVD.IV_LOC_AMT,0)) OVER (PARTITION BY IVD.IV_NO) AS iv_total
    FROM M_IV_DTL IVD
    JOIN M_IV_HDR IVH ON IVH.IV_NO = IVD.IV_NO
    LEFT JOIN B_BIZ_PARTNER B ON B.BP_CD = IVH.BP_CD
    LEFT JOIN B_ITEM BI       ON BI.ITEM_CD = IVD.ITEM_CD
    LEFT JOIN M_IV_TYPE IVT   ON IVT.IV_TYPE_CD = IVH.IV_TYPE_CD
    WHERE IVD.TRACKING_NO = @PJT_CD
  ),
  iv_gl_amt AS (
    SELECT H.REF_NO AS IV_NO,
           SUM(I.ITEM_LOC_AMT) AS GL_DR_AMT,
           MIN(H.GL_NO) AS HDR_GL_NO
    FROM A_GL H JOIN A_GL_ITEM I ON I.GL_NO = H.GL_NO
    WHERE H.GL_INPUT_TYPE = 'AP'
      AND I.PROJECT_NO = @PJT_CD AND I.DR_CR_FG = 'DR'
      AND (I.ACCT_CD LIKE '4%' OR I.ACCT_CD LIKE '52%' OR I.ACCT_CD LIKE '53%' OR I.ACCT_CD LIKE '11%')
    GROUP BY H.REF_NO
  ),
  -- ★ 매입 매핑 사전 (사용자 정정값 그대로)
  iv_item_map AS (
    SELECT 'DIV' AS IV_TYPE_CD, 'A' AS FC, N'제작' AS STAGE, N'부재료' AS ITEM1, N'부재료' AS ITEM2, '410001' AS GP_CD, '41000102' AS ACCT_CD, N'부재료비' AS ACCT_NM
    UNION ALL SELECT 'DIV','R',N'제작',N'원재료',N'원재료','410001','41000101',N'원재료비'
    UNION ALL SELECT 'DIV','S',N'제작',N'부재료',N'표준자재(볼트/너트류)','430025','43002503',N'제)소모품비(자재/기타)'
    UNION ALL SELECT 'IIV','A',N'제작',N'부재료',N'부재료','410001','41000102',N'부재료비'
    UNION ALL SELECT 'IIV','R',N'제작',N'원재료',N'원재료','410001','41000101',N'원재료비'
    UNION ALL SELECT 'LIV','A',N'제작',N'부재료',N'부재료','410001','41000102',N'부재료비'
    UNION ALL SELECT 'RIV','A',N'제작',N'부재료',N'부재료','410001','41000102',N'부재료비'
    UNION ALL SELECT 'RIV','R',N'제작',N'원재료',N'원재료','410001','41000101',N'원재료비'
    UNION ALL SELECT 'SIE','H',N'제작',N'외주가공비',N'외주가공','430037','43003701',N'제)외주가공비(제작)'
    UNION ALL SELECT 'SIE','R',N'제작',N'외주가공비',N'외주가공','430037','43003701',N'제)외주가공비(제작)'
    UNION ALL SELECT 'SIE-1','R',N'제작',N'외주가공비',N'외주가공','430037','43003701',N'제)외주가공비(제작)'
    UNION ALL SELECT 'SIF','R',N'설치',N'외주 용역비',N'외주가공(설치)','460037','46003701',N'제)외주가공비(설치)'
    UNION ALL SELECT 'SIV','H',N'제작',N'외주가공비',N'외주가공','430037','43003701',N'제)외주가공비(제작)'
    UNION ALL SELECT 'SIX','R',N'제작',N'외주용역비',N'수수료','460037','46003701',N'제)외주가공비(설치)'
    UNION ALL SELECT 'XIV','A',N'제작',N'부재료',N'부재료','410001','41000102',N'부재료비'
  )
-- 모드 1: 정상 금액 IV (라인 모드)
-- ★ v9.13 소모품(43002503) 보정: 차변 ABS + 특이사항 '[소모품]' 표기
SELECT
  @PJT_CD                                          AS [계약번호],
  YEAR(CONVERT(date, G.IV_DT))                     AS [연도],
  G.IV_DT                                          AS [회계일자],
  COALESCE(IM.STAGE, N'제작')                      AS [원가 투입 단계],
  COALESCE(IM.ITEM1, N'부재료')                    AS [사용항목1],
  COALESCE(IM.ITEM2, N'부재료')                    AS [사용항목2],
  COALESCE(IM.GP_CD, '410001')                     AS [계정그룹],
  COALESCE(IM.ACCT_NM, N'부재료비')                AS [계정명],
  COALESCE(IM.ACCT_CD, '41000102')                 AS [코드],
  G.BP_NM                                          AS [거래처명],
  CASE WHEN G.PO_NO IS NOT NULL AND LTRIM(RTRIM(G.PO_NO)) <> ''
       THEN N'PO ' + G.PO_NO + N' / ' + COALESCE(G.ITEM_NM,'') + COALESCE(N'/' + NULLIF(G.SPEC,''), '')
       ELSE COALESCE(G.ITEM_NM,'') + COALESCE(N'/' + NULLIF(G.SPEC,''), '') END AS [적요란],
  -- ★ v9.13 소모품 ABS 양수 보정
  CAST(
    CASE WHEN COALESCE(IM.ACCT_CD, '41000102') = '43002503'
         THEN ABS(G.IV_LOC_AMT)
         ELSE G.IV_LOC_AMT END
    AS bigint)                                     AS [차변],
  N''                                              AS [미입고여부],
  -- 추적 컬럼 (HTML/JSON 만, CSV에는 안 들어감)
  G.IV_NO                                          AS [IV번호],
  G.ITEM_CD                                        AS [품목코드],
  G.ITEM_NM                                        AS [품목명],
  G.SPEC                                           AS [규격],
  G.IV_QTY                                         AS [수량],
  G.IV_UNIT                                        AS [단위],
  CAST(G.IV_PRC AS bigint)                         AS [단가],
  CAST(G.VAT_LOC_AMT AS bigint)                    AS [부가세],
  G.PO_NO                                          AS [PO번호],
  G.MVMT_NO                                        AS [수불번호(MVMT)],
  COALESCE(G.IV_TYPE_NM, N'매입')                  AS [자료유형],
  N'AP'                                            AS [전표생성경로],
  G.VOUCHER_NO                                     AS [증빙(결의전표)],
  COALESCE((SELECT TOP 1 H.GL_NO FROM A_GL H
            WHERE H.REF_NO = G.IV_NO AND H.GL_INPUT_TYPE = 'AP'), N'') AS [원인회계전표(GL_NO)],
  -- ★ v9.13 소모품 특이사항
  CASE WHEN COALESCE(IM.ACCT_CD, '41000102') = '43002503' THEN N'[소모품]' ELSE N'' END
                                                   AS [특이사항]
FROM iv_grouped G
LEFT JOIN iv_item_map IM ON IM.IV_TYPE_CD = G.IV_TYPE_CD AND IM.FC = G.FC
WHERE G.iv_total > 0
  AND EXISTS (SELECT 1 FROM A_GL H WHERE H.REF_NO = G.IV_NO AND H.GL_INPUT_TYPE = 'AP')

UNION ALL

-- 모드 2: 헤더 모드 (라인합계=0)
SELECT
  @PJT_CD,
  YEAR(CONVERT(date, G.IV_DT)),
  G.IV_DT,
  COALESCE(IM.STAGE, N'제작'),
  COALESCE(IM.ITEM1, N'부재료'),
  COALESCE(IM.ITEM2, N'부재료'),
  COALESCE(IM.GP_CD, '410001'),
  COALESCE(IM.ACCT_NM, N'부재료비'),
  COALESCE(IM.ACCT_CD, '41000102'),
  G.BP_NM,
  N'(' + @PJT_CD + N',' + COALESCE(G.BP_NM, N'')
    + N' 품목 : ' + COALESCE(G.ITEM_NM, N'')
    + CASE WHEN G.SPEC IS NOT NULL AND G.SPEC <> '' THEN N'/' + G.SPEC ELSE N'' END
    + N' 외 ' + CAST(G.line_cnt - 1 AS nvarchar) + N'건)',
  -- ★ v9.13 소모품 ABS 양수 보정 (헤더모드)
  CAST(
    CASE WHEN COALESCE(IM.ACCT_CD, '41000102') = '43002503'
         THEN ABS(COALESCE(GA.GL_DR_AMT, 0))
         ELSE COALESCE(GA.GL_DR_AMT, 0) END
    AS bigint),
  N'',
  G.IV_NO,
  G.ITEM_CD,
  G.ITEM_NM + CASE WHEN G.line_cnt > 1 THEN N' 외 ' + CAST(G.line_cnt-1 AS nvarchar) + N'건' ELSE N'' END,
  G.SPEC,
  G.IV_QTY,
  G.IV_UNIT,
  CAST(G.IV_PRC AS bigint),
  0,
  G.PO_NO,
  G.MVMT_NO,
  COALESCE(G.IV_TYPE_NM, N'매입'),
  N'AP',
  G.VOUCHER_NO,
  GA.HDR_GL_NO,
  -- ★ v9.13 소모품 특이사항 + 헤더모드 라벨
  CASE WHEN COALESCE(IM.ACCT_CD, '41000102') = '43002503'
       THEN N'[소모품] 헤더모드 (라인합계=0, GL차변금액 적용)'
       ELSE N'헤더모드 (라인합계=0, GL차변금액 적용)' END
FROM iv_grouped G
LEFT JOIN iv_item_map IM ON IM.IV_TYPE_CD = G.IV_TYPE_CD AND IM.FC = G.FC
LEFT JOIN iv_gl_amt GA ON GA.IV_NO = G.IV_NO
WHERE G.iv_total = 0 AND G.rn = 1
  AND GA.HDR_GL_NO IS NOT NULL AND GA.HDR_GL_NO <> ''

ORDER BY [회계일자], [IV번호];


-- =====================================================================
-- Q4. 수불데이터 (v9.13 — OI 만 추출, 소모품은 03 매입에서만 처리)
-- =====================================================================
-- v9.13 변경 (2026-05-18):
--   - v9.12 의 mv_consumable CTE 제거 → 수불은 OI(생산출고) 분개만 추출
--   - 소모품(43002503) PM/IV 분개는 03 매입에서 처리 (Q3 에서 ABS + '[소모품]' 특이사항)
--   - mv_oi 의 'I.ACCT_CD <> 43002503' 조건 제거 → 모든 자재의 OI 동등 처리
WITH
  mov_type_map AS (
    -- MOV_TYPE 한글명 (잠정 사전 — 사용자 정정 대기)
    SELECT 'I01' AS MOV_TYPE, N'구매입고' AS MOV_NM
    UNION ALL SELECT 'I03', N'생산출고(제작)'
    UNION ALL SELECT 'I04', N'생산출고(설치)'
    UNION ALL SELECT 'I31', N'재고이동출고'
    UNION ALL SELECT 'I33', N'재고이동출고'
    UNION ALL SELECT 'I37', N'재고이동출고'
    UNION ALL SELECT 'I38', N'재고이동출고'
    UNION ALL SELECT 'I39', N'재고이동출고'
    UNION ALL SELECT 'I45', N'자재출고'
    UNION ALL SELECT 'I46', N'자재출고'
    UNION ALL SELECT 'I47', N'자재출고'
    UNION ALL SELECT 'I48', N'자재출고'
    UNION ALL SELECT 'I49', N'자재출고'
    UNION ALL SELECT 'I50', N'자재출고'
    UNION ALL SELECT 'I51', N'자재출고'
    UNION ALL SELECT 'I92', N'기타출고'
    UNION ALL SELECT 'I96', N'기타출고'
    UNION ALL SELECT 'I97', N'기타출고'
    UNION ALL SELECT 'I99', N'기타출고'
    UNION ALL SELECT 'I9X', N'임시출고'
    UNION ALL SELECT 'I9Z', N'임시출고'
  ),
  -- ★ 수불 매핑 사전 (사용자 지시값 — 생산출고(제작)/생산출고(설치) + 품목 첫글자별)
  mv_item_map AS (
    SELECT 'I03' AS MOV_TYPE, 'R' AS FC, N'제작' AS STAGE, N'원재료' AS ITEM1, N'원재료' AS ITEM2, '410001' AS GP_CD, '41000101' AS ACCT_CD, N'원재료비' AS ACCT_NM
    UNION ALL SELECT 'I03','A',N'제작',N'부재료',N'부재료','410001','41000102',N'부재료비'
    UNION ALL SELECT 'I03','S',N'제작',N'소모품비',N'소모품비','430025','43002503',N'제)소모품비(자재/기타)'
    UNION ALL SELECT 'I03','H',N'제작',N'가공품',N'가공품','410001','41000102',N'부재료비'
    UNION ALL SELECT 'I03','P',N'제작',N'가공품',N'가공품','410001','41000102',N'부재료비'
    UNION ALL SELECT 'I04','R',N'설치',N'원재료',N'원재료(설치)','440001','44000101',N'원재료비(설치)'
    UNION ALL SELECT 'I04','A',N'설치',N'부재료',N'부재료(설치)','440001','44000102',N'부재료비(설치)'
    UNION ALL SELECT 'I04','S',N'설치',N'소모품비',N'소모품비(설치)','460025','46002503',N'설치)소모품비'
    UNION ALL SELECT 'I04','H',N'설치',N'가공품',N'가공품(설치)','440001','44000102',N'부재료비(설치)'
    UNION ALL SELECT 'I04','P',N'설치',N'가공품',N'가공품(설치)','440001','44000102',N'부재료비(설치)'
  ),
  -- OI(생산출고) 분개만 추출 — 소모품 포함 모든 자재 동등 처리
  mv_oi AS (
    SELECT
      @PJT_CD AS PROJECT_NO,
      CONVERT(varchar(10), I.GL_DT, 120) AS GL_DT,
      I.GL_NO, I.ITEM_SEQ,
      H.REF_NO,
      LEFT(H.REF_NO, CHARINDEX('-', H.REF_NO) - 1) AS GM_NO,
      I.ACCT_CD AS GL_ACCT_CD, AC.ACCT_NM AS GL_ACCT_NM, AC.GP_CD AS GL_ACCT_GP_CD,
      I.ITEM_LOC_AMT AS AMT,
      H.GL_DESC AS HDR_DESC,
      I.ITEM_DESC,
      GH.MOV_TYPE,
      MTM.MOV_NM,
      DTL.ITEM_CD, BI.ITEM_NM, BI.SPEC,
      LEFT(COALESCE(DTL.ITEM_CD,''), 1) AS FC
    FROM A_GL H
    JOIN A_GL_ITEM I ON I.GL_NO = H.GL_NO
    LEFT JOIN A_ACCT AC ON AC.ACCT_CD = I.ACCT_CD
    LEFT JOIN A_ACCT_GP GP ON GP.GP_CD = AC.GP_CD
    INNER JOIN I_GOODS_MOVEMENT_HEADER GH
      ON GH.ITEM_DOCUMENT_NO = LEFT(H.REF_NO, CHARINDEX('-', H.REF_NO) - 1)
      AND GH.DOCUMENT_YEAR    = SUBSTRING(H.REF_NO, CHARINDEX('-', H.REF_NO) + 1, 10)
      AND GH.ITEM_DOCUMENT_NO LIKE 'OI%'
    LEFT JOIN mov_type_map MTM ON MTM.MOV_TYPE = GH.MOV_TYPE
    OUTER APPLY (
      SELECT TOP 1 D.ITEM_CD
      FROM I_GOODS_MOVEMENT_DETAIL D
      WHERE D.ITEM_DOCUMENT_NO = GH.ITEM_DOCUMENT_NO
        AND D.DOCUMENT_YEAR    = GH.DOCUMENT_YEAR
      ORDER BY D.SEQ_NO
    ) DTL
    LEFT JOIN B_ITEM BI ON BI.ITEM_CD = DTL.ITEM_CD
    WHERE H.GL_INPUT_TYPE = 'IM'
      AND I.PROJECT_NO = @PJT_CD
      AND CHARINDEX('-', H.REF_NO) > 0
      AND I.GL_NO IS NOT NULL AND I.GL_NO <> ''
  )
SELECT
  @PJT_CD                                          AS [계약번호],
  YEAR(CONVERT(date, M.GL_DT))                     AS [연도],
  M.GL_DT                                          AS [회계일자],
  COALESCE(IM.STAGE, N'제작')                      AS [원가 투입 단계],
  COALESCE(IM.ITEM1, N'원재료')                    AS [사용항목1],
  COALESCE(IM.ITEM2, N'원재료')                    AS [사용항목2],
  COALESCE(IM.GP_CD, '410001')                     AS [계정그룹],
  COALESCE(IM.ACCT_NM, N'원재료비')                AS [계정명],
  COALESCE(IM.ACCT_CD, '41000101')                 AS [코드],
  COALESCE(M.ITEM_NM, N'')                         AS [거래처명],
  CASE
    WHEN (M.HDR_DESC IS NULL OR LTRIM(RTRIM(M.HDR_DESC)) = '')
      THEN COALESCE(LTRIM(RTRIM(M.ITEM_DESC)), '')
    WHEN (M.ITEM_DESC IS NULL OR LTRIM(RTRIM(M.ITEM_DESC)) = '')
      THEN LTRIM(RTRIM(M.HDR_DESC))
    WHEN LTRIM(RTRIM(M.HDR_DESC)) = LTRIM(RTRIM(M.ITEM_DESC))
      THEN LTRIM(RTRIM(M.ITEM_DESC))
    ELSE LTRIM(RTRIM(M.HDR_DESC)) + N' / ' + LTRIM(RTRIM(M.ITEM_DESC))
  END                                              AS [적요란],
  CAST(M.AMT AS bigint)                            AS [차변],
  N''                                              AS [미입고여부],
  M.ITEM_CD                                        AS [품목코드],
  M.ITEM_NM                                        AS [품목명],
  M.SPEC                                           AS [규격],
  N'MV'                                            AS [구분],
  COALESCE(M.MOV_NM, N'수불 (' + COALESCE(M.MOV_TYPE, N'?') + N')') AS [자료유형],
  N'IM'                                            AS [전표생성경로],
  M.GM_NO                                          AS [증빙번호],
  M.GL_NO                                          AS [원인회계전표(GL_NO)],
  N'수불 ' + M.GM_NO + N' (' + COALESCE(M.MOV_NM, N'MOV_TYPE=' + COALESCE(M.MOV_TYPE, N'?')) + N')' AS [특이사항]
FROM mv_oi M
LEFT JOIN mv_item_map IM ON IM.MOV_TYPE = M.MOV_TYPE AND IM.FC = M.FC
ORDER BY [회계일자], [원인회계전표(GL_NO)];


-- =====================================================================
-- 검증 쿼리 (선택)
-- =====================================================================
-- 행수 빠르게 확인:
-- DECLARE @PJT_CD nvarchar(50) = N'2024-056-SCH';
-- SELECT
--   (SELECT COUNT(*) FROM A_GL_ITEM I JOIN A_GL H ON H.GL_NO=I.GL_NO
--     WHERE I.PROJECT_NO=@PJT_CD AND I.DR_CR_FG='DR'
--       AND (I.ACCT_CD LIKE '4%' OR I.ACCT_CD LIKE '52%' OR I.ACCT_CD LIKE '53%')
--       AND H.GL_INPUT_TYPE NOT IN ('AP','IM')) AS cost_v9,
--   (SELECT COUNT(*) FROM M_IV_DTL WHERE TRACKING_NO=@PJT_CD) AS iv_total_lines,
--   (SELECT COUNT(DISTINCT IV_NO) FROM M_IV_DTL WHERE TRACKING_NO=@PJT_CD
--     GROUP BY IV_NO HAVING SUM(COALESCE(IV_LOC_AMT,0))=0) AS iv_zero_total_count
