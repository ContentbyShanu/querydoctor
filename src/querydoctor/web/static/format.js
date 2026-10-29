export function ms(value) {
  if (value == null) return "n/a";
  if (value >= 100) return `${Math.round(value).toLocaleString()} ms`;
  if (value >= 10) return `${value.toFixed(0)} ms`;
  if (value >= 1) return `${value.toFixed(1)} ms`;
  return `${value.toFixed(2)} ms`;
}

export function speedup(value) {
  if (value == null) return "n/a";
  return value >= 10 ? `${Math.round(value).toLocaleString()}x` : `${value.toFixed(1)}x`;
}

export function bytes(value) {
  if (value == null) return "n/a";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i += 1;
  }
  return `${i < 2 ? Math.round(size) : size.toFixed(1)} ${units[i]}`;
}

export function percent(fraction) {
  return `${Math.round(fraction * 100)}%`;
}

export function number(value) {
  return Number(value).toLocaleString();
}
