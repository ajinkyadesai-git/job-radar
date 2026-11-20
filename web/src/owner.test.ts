import { beforeEach, describe, expect, it } from "vitest";
import { clearOwnerKey, currentOwnerKey, saveOwnerKey } from "./owner";

describe("owner passphrase", () => {
  beforeEach(() => clearOwnerKey());

  it("is absent until saved", () => {
    expect(currentOwnerKey()).toBeNull();
  });

  it("is kept after saving and gone after locking", () => {
    saveOwnerKey("secret");
    expect(currentOwnerKey()).toBe("secret");
    clearOwnerKey();
    expect(currentOwnerKey()).toBeNull();
  });
});
