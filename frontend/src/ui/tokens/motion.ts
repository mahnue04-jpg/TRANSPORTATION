export const motion = {
  duration: {
    fast: "140ms",
    medium: "240ms",
    slow: "420ms",
  },
  easing: {
    standard: "cubic-bezier(0.22, 0.61, 0.36, 1)",
    emphasized: "cubic-bezier(0.2, 0.8, 0.2, 1)",
  },
  keyframes: {
    fadeIn: "amicorFadeIn",
    messageIn: "amicorMessageIn",
  },
} as const;

export type MotionDurationToken = keyof typeof motion.duration;
