export function formatMs(value: number | null): string {
  return value === null ? "—" : `${Math.round(value).toLocaleString()} ms`;
}
