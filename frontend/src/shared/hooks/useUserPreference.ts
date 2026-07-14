import { useCallback, useState } from 'react';

function storageKey(userId: string, key: string): string {
  return `openscience:preference:${userId}:${key}`;
}

export function useUserPreference<T>(
  userId: string,
  key: string,
  defaultValue: T,
  validate: (value: unknown) => value is T,
): [T, (value: T | ((current: T) => T)) => void] {
  const read = useCallback((): T => {
    try {
      const raw = window.localStorage.getItem(storageKey(userId, key));
      if (raw !== null) {
        const parsed: unknown = JSON.parse(raw);
        if (validate(parsed)) return parsed;
      }
    } catch {
      // Fall back to the product default when storage is unavailable or corrupt.
    }
    return defaultValue;
  }, [defaultValue, key, userId, validate]);

  const [value, setValue] = useState<T>(read);

  const update = useCallback((next: T | ((current: T) => T)) => {
    setValue((current) => {
      const resolved = typeof next === 'function'
        ? (next as (current: T) => T)(current)
        : next;
      try {
        window.localStorage.setItem(storageKey(userId, key), JSON.stringify(resolved));
      } catch {
        // The in-memory preference remains usable for this session.
      }
      return resolved;
    });
  }, [key, userId]);

  return [value, update];
}
