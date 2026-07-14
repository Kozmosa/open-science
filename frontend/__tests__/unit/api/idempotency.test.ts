import { act, renderHook } from '@testing-library/react';
import {
  IdempotencyKeyManager,
  semanticMutationValue,
  useIdempotencyKey,
} from '@/shared/api/idempotency';

describe('IdempotencyKeyManager', () => {
  it('reuses a key for the same semantic submission and rotates on change or success', () => {
    const manager = new IdempotencyKeyManager('task.create');
    const first = manager.keyFor(semanticMutationValue({ prompt: 'alpha', project: 'one' }));
    const replay = manager.keyFor(semanticMutationValue({ project: 'one', prompt: 'alpha' }));
    const changed = manager.keyFor(semanticMutationValue({ prompt: 'beta', project: 'one' }));

    expect(replay).toBe(first);
    expect(changed).not.toBe(first);

    manager.markSucceeded();
    expect(manager.keyFor(semanticMutationValue({ prompt: 'beta', project: 'one' })))
      .not.toBe(changed);
  });
});

describe('useIdempotencyKey', () => {
  it('keeps the current attempt key stable and exposes success rotation', () => {
    const { result, rerender } = renderHook(
      ({ prompt }) => useIdempotencyKey('task.create', { prompt }),
      { initialProps: { prompt: 'alpha' } },
    );
    const first = result.current.idempotencyKey;

    rerender({ prompt: 'alpha' });
    expect(result.current.idempotencyKey).toBe(first);

    rerender({ prompt: 'beta' });
    const changed = result.current.idempotencyKey;
    expect(changed).not.toBe(first);

    act(() => result.current.markSucceeded());
    expect(result.current.idempotencyKey).not.toBe(changed);
  });
});
