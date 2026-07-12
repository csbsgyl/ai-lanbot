export function maskIdentifier(value: string): string {
  if (!value) return '-';
  if (value.length <= 4) return '****';
  if (value.length <= 7) return `${value.slice(0, 1)}***${value.slice(-1)}`;
  return `${value.slice(0, 3)}***${value.slice(-2)}`;
}

export function formatTimestamp(value: string): string {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
