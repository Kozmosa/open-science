export function readMigratedLocalStorage(primaryKey: string, legacyKeys: string[]): string | null {
  const current = window.localStorage.getItem(primaryKey);
  if (current !== null) {
    return current;
  }

  for (const legacyKey of legacyKeys) {
    const legacy = window.localStorage.getItem(legacyKey);
    if (legacy !== null) {
      window.localStorage.setItem(primaryKey, legacy);
      window.localStorage.removeItem(legacyKey);
      return legacy;
    }
  }

  return null;
}


export function removeLocalStorage(primaryKey: string, legacyKeys: string[]): void {
  window.localStorage.removeItem(primaryKey);
  for (const legacyKey of legacyKeys) {
    window.localStorage.removeItem(legacyKey);
  }
}
