export const ARCHIVED_PRE_CLOSE_STRATEGY_VERSION = "preclose-1445-v2";
export const CURRENT_PRE_CLOSE_STRATEGY_VERSION = "preclose-1445-v3";
export const SUPPORTED_PRE_CLOSE_STRATEGY_VERSIONS = [
  ARCHIVED_PRE_CLOSE_STRATEGY_VERSION,
  CURRENT_PRE_CLOSE_STRATEGY_VERSION,
] as const;

export function isSupportedPrecloseStrategyVersion(
  value: unknown,
): value is (typeof SUPPORTED_PRE_CLOSE_STRATEGY_VERSIONS)[number] {
  return typeof value === "string"
    && (SUPPORTED_PRE_CLOSE_STRATEGY_VERSIONS as readonly string[]).includes(value);
}
