export const RESOURCE_REFRESH_MS = 5_000;
export const RESOURCE_STALE_MS = 15_000;

export function resourceRefreshInterval(visible: boolean): number | false {
  return visible ? RESOURCE_REFRESH_MS : false;
}
