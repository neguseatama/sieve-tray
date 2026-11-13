// 集計表の部品（本体のアプリから一つの関数だけを取り出したものです）。
function countByStatus(rows) {
  const out = { done: 0, open: 0, held: 0 };
  for (const r of rows) {
    if (r.status === "done") out.done += 1;
    else if (r.status === "open") out.open += 1;
    else out.held += 1;
  }
  return out;
}
