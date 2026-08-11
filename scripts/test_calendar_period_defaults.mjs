import { previousCompletePeriods } from '../admin-panel/js/calendar-periods.mjs';

function check(condition, message) {
  if (!condition) throw new Error(message);
}

for (let day = 10; day <= 16; day += 1) {
  const today = `2026-08-${String(day).padStart(2, '0')}`;
  const value = previousCompletePeriods(today);
  check(value.weekStart === '2026-08-03', `${today} weekStart=${value.weekStart}`);
  check(value.weekEnd === '2026-08-09', `${today} weekEnd=${value.weekEnd}`);
  check(value.month === '2026-07', `${today} month=${value.month}`);
  check(value.quarter === '2026-Q2', `${today} quarter=${value.quarter}`);
  check(value.year === '2025', `${today} year=${value.year}`);
}

const jan = previousCompletePeriods('2026-01-01');
check(jan.month === '2025-12', `January rollover month=${jan.month}`);
check(jan.quarter === '2025-Q4', `January rollover quarter=${jan.quarter}`);
check(jan.year === '2025', `January rollover year=${jan.year}`);

const april = previousCompletePeriods('2026-04-01');
check(april.quarter === '2026-Q1', `April rollover quarter=${april.quarter}`);

console.log('PASS: admin calendar defaults use previous complete periods');
