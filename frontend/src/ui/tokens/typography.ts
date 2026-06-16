export const typography = {
  fontFamily: {
    primary: '"Segoe UI", system-ui, -apple-system, sans-serif',
    mono: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Courier New", monospace',
  },
  size: {
    xs: "0.62rem",
    sm: "0.74rem",
    md: "0.9rem",
    lg: "1.06rem",
    xl: "1.22rem",
  },
  lineHeight: {
    compact: 1.3,
    normal: 1.55,
    reading: 1.72,
  },
  weight: {
    regular: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
} as const;
