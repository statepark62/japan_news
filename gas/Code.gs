/**
 * 일본 뉴스 파이프라인 — 범용 시트 수집 웹앱 v2.3 (Google Apps Script)
 * © 2026 박상태 (Sangtae Park)
 *
 * v2.2 → v2.3 변경점:
 *  ★ id 자동채번 모드(단어 수집)에 레벨 필터 추가 — N3·N4·N5만 시트에 기록.
 *    N2·N1로 표시된 단어는 조용히 걸러지고(filtered 카운트로 응답), 시트에 쓰이지 않습니다.
 *    AI가 프롬프트 지시를 놓치고 N1·N2를 골라도 여기서 최종 차단되는 안전장치입니다.
 *    (레벨 정책을 나중에 다시 바꾸고 싶으면 ALLOWED_LEVELS 배열만 수정하면 됩니다.)
 *
 * 그 외 기능은 v2.2와 동일:
 *  · doPost 일반 모드      — { secret, sheet, headers, rows, dedupIndex }
 *  · doPost id 자동채번 모드 — { ..., idPrefix: "tj" | "news" } : ことば帖 단어장에 이어 붙임
 *        중복 판정: 단어+읽기+예문
 *  · doGet  ?action=visit&t=new|ret|count — 방문 집계 (비밀값 불필요, 검사보다 위)
 *  · doGet  ?action=export&secret=...     — 단어장 전체를 PWA용 JSON으로 내보내기
 *
 * ★ 저장 후 반드시: 배포 → 배포 관리 → 연필 → 버전 "새 버전" → 배포
 */

const SHEET_ID = "1yhLue1LFEuJ01cfYAjdGDszdbaAeUn5TXdB52a8CTB0";
const SHARED_SECRET = "jpnews-864354d3772a0883d382336d2b0b50f5";   // ★ 지금 쓰는 값 그대로
const TZ = "Asia/Seoul";
const WORDS_SHEET = "단어장";
const ALLOWED_LEVELS = ["N5", "N4", "N3"];   // ★ 자동 수집 허용 레벨 (정책 변경 시 여기만 수정)

/* ══════════════════ 수집 (doPost) ══════════════════ */

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.secret !== SHARED_SECRET) {
      return json_({ ok: false, error: "unauthorized" });
    }
    const sheetName = body.sheet;
    if (!sheetName) return json_({ ok: false, error: "no sheet name" });

    const rows = body.rows || [];
    const dedupIndex = (body.dedupIndex === undefined) ? null : body.dedupIndex;
    const idPrefix = body.idPrefix || null;

    const ss = SpreadsheetApp.openById(SHEET_ID);
    let sh = ss.getSheetByName(sheetName);

    if (idPrefix) {
      return json_(appendWithId_(sh, sheetName, rows, idPrefix));
    }
    return json_(appendPlain_(ss, sh, sheetName, body.headers || [], rows, dedupIndex));
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

/* (1) 일반 모드 */
function appendPlain_(ss, sh, sheetName, headers, rows, dedupIndex) {
  if (!sh) {
    sh = ss.insertSheet(sheetName);
    if (headers.length) { sh.appendRow(headers); sh.setFrozenRows(1); }
  }
  const seen = {};
  if (dedupIndex !== null && sh.getLastRow() > 1) {
    const vals = sh.getRange(2, dedupIndex + 1, sh.getLastRow() - 1, 1).getValues();
    vals.forEach(function (r) { seen[String(r[0])] = true; });
  }
  const toWrite = [];
  rows.forEach(function (row) {
    if (dedupIndex !== null) {
      const key = String(row[dedupIndex]);
      if (seen[key]) return;
      seen[key] = true;
    }
    toWrite.push(row);
  });
  if (toWrite.length) {
    sh.getRange(sh.getLastRow() + 1, 1, toWrite.length, toWrite[0].length).setValues(toWrite);
  }
  return { ok: true, sheet: sheetName, added: toWrite.length };
}

/* (2) id 자동채번 모드 — 중복 판정: 단어+읽기+예문, 레벨 필터: N3~N5만 */
function appendWithId_(sh, sheetName, rows, idPrefix) {
  if (!sh) return { ok: false, error: "단어장 시트를 찾을 수 없음: " + sheetName };

  const lastRow = sh.getLastRow();

  let maxNum = 0;
  const seenKey = {};
  if (lastRow > 1) {
    const data = sh.getRange(2, 1, lastRow - 1, 6).getValues(); // A(id)~F(예문)
    const re = new RegExp("^" + idPrefix + "(\\d+)$");
    data.forEach(function (r) {
      const m = re.exec(String(r[0]));
      if (m) { const num = parseInt(m[1], 10); if (num > maxNum) maxNum = num; }
      seenKey[String(r[1]) + "|" + String(r[2]) + "|" + String(r[5])] = true;
    });
  }

  const today = Utilities.formatDate(new Date(), TZ, "yyyy. M. d");
  const toWrite = [];
  let num = maxNum;
  let filtered = 0;
  rows.forEach(function (row) {
    // rows: [단어, 읽기, 의미, 레벨, 예문, 예문읽기, 예문뜻]
    const level = String(row[3] || "").toUpperCase();
    if (ALLOWED_LEVELS.indexOf(level) === -1) { filtered++; return; }   // ★ N2·N1 등 여기서 차단

    const key = String(row[0]) + "|" + String(row[1]) + "|" + String(row[4]);
    if (!row[0] || !row[1] || seenKey[key]) return;
    seenKey[key] = true;
    num++;
    toWrite.push([idPrefix + num].concat(row).concat([today]));
  });

  if (toWrite.length) {
    sh.getRange(lastRow + 1, 1, toWrite.length, toWrite[0].length).setValues(toWrite);
  }
  return { ok: true, sheet: sheetName, added: toWrite.length, filtered: filtered, nextId: idPrefix + num };
}

/* ══════════════════ 조회 (doGet) ══════════════════ */

function doGet(e) {
  try {
    const p = e.parameter || {};

    // 방문 집계: 비밀값 불필요 → 반드시 검사보다 위
    if (p.action === "visit") return json_(recordVisit_(p.t));

    if (p.secret !== SHARED_SECRET) return json_({ ok: false, error: "unauthorized" });

    if (p.action === "export") {
      const sh = SpreadsheetApp.openById(SHEET_ID).getSheetByName(WORDS_SHEET);
      if (!sh) return json_({ ok: false, error: "단어장 시트 없음" });
      const last = sh.getLastRow();
      const words = [];
      if (last > 1) {
        const data = sh.getRange(2, 1, last - 1, 8).getValues();
        data.forEach(function (r) {
          if (!r[1] || !r[2]) return;
          words.push({
            id: String(r[0]),
            word: String(r[1]),
            reading: String(r[2]),
            meaning: String(r[3]),
            level: String(r[4] || "기타"),
            example: String(r[5] || ""),
            exampleReading: String(r[6] || ""),
            exampleMeaning: String(r[7] || ""),
          });
        });
      }
      return json_(words);
    }
    return json_({ ok: false, error: "unknown action" });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

/* ══════════════════ 방문 집계 ══════════════════ */

function recordVisit_(t) {
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {
    const ss = SpreadsheetApp.openById(SHEET_ID);
    let sh = ss.getSheetByName("방문기록");
    if (!sh) {
      sh = ss.insertSheet("방문기록");
      sh.appendRow(["날짜", "방문수", "신규방문"]);
      sh.setFrozenRows(1);
    }

    const today = Utilities.formatDate(new Date(), TZ, "yyyy-MM-dd");
    const lastRow = sh.getLastRow();
    let row = -1, visits = 0, news = 0, total = 0;

    if (lastRow > 1) {
      const data = sh.getRange(2, 1, lastRow - 1, 2).getValues();
      for (let i = 0; i < data.length; i++) total += Number(data[i][1]) || 0;
      const last = sh.getRange(lastRow, 1, 1, 3).getValues()[0];
      if (String(last[0]) === today) {
        row = lastRow;
        visits = Number(last[1]) || 0;
        news = Number(last[2]) || 0;
      }
    }

    if (t === "new" || t === "ret") {
      visits++;
      if (t === "new") news++;
      total++;
      if (row === -1) sh.appendRow([today, visits, news]);
      else sh.getRange(row, 2, 1, 2).setValues([[visits, news]]);
    } else if (row === -1) {
      visits = 0;
    }

    return { ok: true, date: today, today: visits, total: total };
  } finally {
    lock.releaseLock();
  }
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
