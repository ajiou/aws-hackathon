export const number = (value: number) =>
  value.toLocaleString("zh-TW", { maximumFractionDigits: 1 });
export const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
export function isoWeek(date = new Date()) {
  const d = new Date(
    Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()),
  );
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return `${d.getUTCFullYear()}-W${String(Math.ceil(((+d - +yearStart) / 86400000 + 1) / 7)).padStart(2, "0")}`;
}
