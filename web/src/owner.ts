// The owner's passphrase, kept only in this browser (never in the code or the build).
const KEY = "jobradar.owner";

export function ownerKey(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null; // storage blocked (private window): the site still works, just locked
  }
}

export function saveOwnerKey(value: string): void {
  try {
    window.localStorage.setItem(KEY, value);
  } catch {
    /* not remembered; unlocks this visit only via memory below */
  }
  memory = value;
}

export function clearOwnerKey(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* nothing stored */
  }
  memory = null;
}

let memory: string | null = null;

export function currentOwnerKey(): string | null {
  return memory ?? ownerKey();
}
