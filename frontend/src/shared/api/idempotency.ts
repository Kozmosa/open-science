import { useCallback, useMemo, useReducer } from 'react';

function fallbackUuid(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function createIdempotencyKey(scope: string): string {
  const normalizedScope = scope.trim().replace(/[^a-zA-Z0-9._-]+/g, '-').slice(0, 80) || 'mutation';
  const uuid = typeof globalThis.crypto.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : fallbackUuid();
  return `${normalizedScope}:${uuid}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export function semanticMutationValue(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

export class IdempotencyKeyManager {
  private readonly scope: string;
  private key: string;
  private semanticValue: string | null = null;

  constructor(scope: string) {
    this.scope = scope;
    this.key = createIdempotencyKey(scope);
  }

  keyFor(semanticValue: string): string {
    if (this.semanticValue !== null && this.semanticValue !== semanticValue) {
      this.key = createIdempotencyKey(this.scope);
    }
    this.semanticValue = semanticValue;
    return this.key;
  }

  markSucceeded(): void {
    this.key = createIdempotencyKey(this.scope);
    this.semanticValue = null;
  }
}

export function idempotencyHeaders(idempotencyKey: string): HeadersInit {
  return { 'Idempotency-Key': idempotencyKey };
}

export function useIdempotencyKey(scope: string, semanticValue: unknown) {
  const [generation, rotate] = useReducer((count: number) => count + 1, 0);
  const serialized = semanticMutationValue(semanticValue);
  const idempotencyKey = useMemo(
    () => createIdempotencyKey(`${scope}.${generation}.${serialized.length}`),
    [generation, scope, serialized],
  );
  const markSucceeded = useCallback(() => rotate(), []);

  return { idempotencyKey, markSucceeded } as const;
}
