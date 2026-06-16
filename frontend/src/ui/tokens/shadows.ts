export const shadows = {
  soft: "0 8px 24px rgba(0, 0, 0, 0.28)",
  card: "0 10px 28px rgba(0, 0, 0, 0.32)",
  hover: "0 12px 24px rgba(0, 0, 0, 0.28)",
  glow: "0 0 16px rgba(108, 99, 255, 0.3)",
} as const;

export type ShadowToken = keyof typeof shadows;
