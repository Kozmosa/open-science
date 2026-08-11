export const USERNAME_MIN_LENGTH = 2;
export const USERNAME_MAX_LENGTH = 31;
export const USERNAME_PATTERN = '[a-z0-9][a-z0-9_-]{1,30}';

const usernamePattern = new RegExp(`^${USERNAME_PATTERN}$`);

export function normalizeUsernameInput(value: string): string {
  return value.replace(/[^a-z0-9_-]/g, '').slice(0, USERNAME_MAX_LENGTH);
}

export function isValidUsername(value: string): boolean {
  return usernamePattern.test(value);
}
