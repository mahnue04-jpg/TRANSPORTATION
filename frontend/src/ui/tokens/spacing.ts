export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 28,
} as const;

export type SpacingToken = keyof typeof spacing;

export function space(token: SpacingToken): string {
  return `${spacing[token]}px`;
}
