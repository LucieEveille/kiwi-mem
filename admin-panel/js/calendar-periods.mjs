function parseIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`invalid ISO date: ${value}`);
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new Error(`invalid ISO date: ${value}`);
  }
  return parsed;
}

function addDays(value, days) {
  const copy = new Date(value.getTime());
  copy.setUTCDate(copy.getUTCDate() + days);
  return copy;
}

function isoDate(value) { return value.toISOString().slice(0, 10); }
function isoMonth(value) { return value.toISOString().slice(0, 7); }

export function previousCompletePeriods(todayValue) {
  const today = parseIsoDate(todayValue);
  const mondayIndex = (today.getUTCDay() + 6) % 7;
  const weekEnd = addDays(today, -(mondayIndex + 1));
  const weekStart = addDays(weekEnd, -6);

  const monthStart = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
  const previousMonth = addDays(monthStart, -1);

  const currentQuarter = Math.floor(today.getUTCMonth() / 3) + 1;
  const previousQuarter = currentQuarter === 1 ? 4 : currentQuarter - 1;
  const previousQuarterYear = currentQuarter === 1 ? today.getUTCFullYear() - 1 : today.getUTCFullYear();

  return {
    weekStart: isoDate(weekStart),
    weekEnd: isoDate(weekEnd),
    month: isoMonth(previousMonth),
    quarter: `${previousQuarterYear}-Q${previousQuarter}`,
    year: String(today.getUTCFullYear() - 1),
  };
}
