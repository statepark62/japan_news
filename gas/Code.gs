/**
 * 일본 뉴스 파이프라인 — 범용 시트 수집 웹앱 (Google Apps Script)
 * collect.py 가 { secret, sheet, headers, rows, dedupIndex } 를 POST 하면
 * 지정한 시트에 행을 누적한다(dedupIndex 열 기준 중복 제거).
 * 하나의 웹앱으로 "뉴스기록", "단어장" 등 여러 시트를 모두 처리한다.
 *
 * 배포
 *  1) 스프레드시트 생성 → URL 의 /d/ 와 /edit 사이 값이 SHEET_ID.
 *  2) 확장 프로그램 → Apps Script → 이 코드 붙여넣기.
 *  3) SHEET_ID, SHARED_SECRET 채우기.
 *  4) 배포 → 새 배포 → "웹 앱" → 실행: 본인 / 액세스: 모든 사용자 → 배포.
 *  5) 웹앱 URL → Secret GAS_SHEET_URL,  SHARED_SECRET → Secret GAS_SHARED_SECRET.
 */

const SHEET_ID = "여기에_스프레드시트_ID";
const SHARED_SECRET = "여기에_임의의_긴_비밀문자열";  // collect.py 와 동일하게

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.secret !== SHARED_SECRET) {
      return json_({ ok: false, error: "unauthorized" });
    }

    const sheetName = body.sheet;
    const headers = body.headers || [];
    const rows = body.rows || [];
    const dedupIndex = (body.dedupIndex === undefined) ? null : body.dedupIndex;

    if (!sheetName) return json_({ ok: false, error: "no sheet name" });

    const ss = SpreadsheetApp.openById(SHEET_ID);
    let sh = ss.getSheetByName(sheetName);
    if (!sh) {
      sh = ss.insertSheet(sheetName);
      if (headers.length) {
        sh.appendRow(headers);
        sh.setFrozenRows(1);
      }
    }

    // 중복 방지: dedupIndex 열의 기존 값 수집
    const seen = {};
    if (dedupIndex !== null && sh.getLastRow() > 1) {
      const vals = sh.getRange(2, dedupIndex + 1, sh.getLastRow() - 1, 1).getValues();
      vals.forEach(function (r) { seen[String(r[0])] = true; });
    }

    let added = 0;
    const toWrite = [];
    rows.forEach(function (row) {
      if (dedupIndex !== null) {
        const key = String(row[dedupIndex]);
        if (seen[key]) return;
        seen[key] = true;
      }
      toWrite.push(row);
      added++;
    });

    if (toWrite.length) {
      sh.getRange(sh.getLastRow() + 1, 1, toWrite.length, toWrite[0].length).setValues(toWrite);
    }
    return json_({ ok: true, sheet: sheetName, added: added });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
