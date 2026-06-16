export const colors = {
  background: "#0b0b10",
  surface: "#13131c",
  surfaceElevated: "#1c1c28",
  surfaceStrong: "#252535",
  border: "#2a2a3e",
  borderStrong: "#353550",
  accent: "#6c63ff",
  accentLight: "#8b85ff",
  accentGlow: "rgba(108, 99, 255, 0.3)",
  text: "#e9e9f4",
  textDim: "#9494b8",
  textMuted: "#5c5c7e",
  success: "#43c98a",
  warning: "#f5a623",
  error: "#ff5f72",
} as const;

export type ColorToken = keyof typeof colors;
