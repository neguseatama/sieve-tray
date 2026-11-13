// 提出物の集計表を作る小さなアプリです。
function makeHeader(title) {
  const bar = document.createElement("div");
  bar.className = "bar";
  const label = document.createElement("span");
  label.textContent = title;
  bar.appendChild(label);
  return bar;
}

function countByStatus(rows) {
  const out = { done: 0, open: 0, held: 0 };
  for (const r of rows) {
    if (r.status === "done") out.done += 1;
    else if (r.status === "open") out.open += 1;
    else out.held += 1;
  }
  return out;
}

function buildRow(name, n) {
  const tr = document.createElement("tr");
  const tdName = document.createElement("td");
  const tdN = document.createElement("td");
  tdName.textContent = name;
  tdN.textContent = String(n);
  tr.appendChild(tdName);
  tr.appendChild(tdN);
  return tr;
}

function renderTable(rows) {
  const table = document.createElement("table");
  for (const r of rows) {
    table.appendChild(buildRow(r.name, r.score));
  }
  return table;
}

function mountAll(root, rows) {
  root.appendChild(makeHeader("提出物の集計"));
  const counts = countByStatus(rows);
  root.appendChild(buildRow("done", counts.done));
  root.appendChild(buildRow("open", counts.open));
  root.appendChild(buildRow("held", counts.held));
  root.appendChild(renderTable(rows));
}
