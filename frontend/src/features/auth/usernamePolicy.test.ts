import { describe, expect, it } from 'vitest';

import { isValidUsername, normalizeUsernameInput } from './usernamePolicy';

describe('usernamePolicy', () => {
  it('accepts only canonical Linux tenant-safe usernames', () => {
    expect(isValidUsername('a0')).toBe(true);
    expect(isValidUsername('alice_01-test')).toBe(true);
    expect(isValidUsername('a'.repeat(31))).toBe(true);
  });

  it('rejects values outside the canonical contract', () => {
    expect(isValidUsername('a')).toBe(false);
    expect(isValidUsername('_alice')).toBe(false);
    expect(isValidUsername('Alice')).toBe(false);
    expect(isValidUsername('alice.test')).toBe(false);
    expect(isValidUsername('a'.repeat(32))).toBe(false);
  });

  it('normalizes browser input without exceeding the maximum length', () => {
    expect(normalizeUsernameInput('Alice.test_name-' + 'x'.repeat(40))).toBe(
      ('licetest_name-' + 'x'.repeat(40)).slice(0, 31),
    );
  });
});
