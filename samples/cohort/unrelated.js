// 日付の表示を整えるための小さな道具集です。
function padTwo(n) {
  return (n < 10 ? "0" : "") + n;
}

function formatStamp(d) {
  const y = d.getFullYear();
  const mo = padTwo(d.getMonth() + 1);
  const da = padTwo(d.getDate());
  const hh = padTwo(d.getHours());
  const mi = padTwo(d.getMinutes());
  return y + "-" + mo + "-" + da + " " + hh + ":" + mi;
}

function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

function isLeapYear(year) {
  if (year % 400 === 0) return true;
  if (year % 100 === 0) return false;
  return year % 4 === 0;
}
