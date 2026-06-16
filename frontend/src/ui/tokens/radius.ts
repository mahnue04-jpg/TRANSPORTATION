export const radius = {
  sm: "10px",
  md: "18px",
  lg: "22px",
  pill: "999px",
} as const;

export type RadiusToken = keyof typeof radius;
