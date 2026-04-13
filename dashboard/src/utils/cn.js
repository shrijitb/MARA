/** Merge Tailwind class names, filtering out falsy values. */
export function cn(...classes) {
  return classes.filter(Boolean).join(' ');
}
