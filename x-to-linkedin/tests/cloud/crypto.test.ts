import { describe, expect, it } from "vitest";
import {
  decodeKey,
  decryptSecret,
  encryptSecret,
  rotateSecret
} from "../../cloud/src/crypto.js";

describe("credential encryption", () => {
  it("encrypts with a unique nonce and decrypts", () => {
    const key = Buffer.alloc(32, 7);
    const first = encryptSecret("token-value", key);
    const second = encryptSecret("token-value", key);
    expect(first.iv).not.toBe(second.iv);
    expect(first.data).not.toContain("token-value");
    expect(decryptSecret(first, key)).toBe("token-value");
  });

  it("rotates keys and rejects the old key", () => {
    const oldKey = Buffer.alloc(32, 1);
    const newKey = Buffer.alloc(32, 2);
    const rotated = rotateSecret(encryptSecret("secret", oldKey), oldKey, newKey);
    expect(decryptSecret(rotated, newKey)).toBe("secret");
    expect(() => decryptSecret(rotated, oldKey)).toThrow();
  });

  it("accepts only 32 byte key material", () => {
    expect(decodeKey(Buffer.alloc(32, 3).toString("base64"))).toHaveLength(32);
    expect(() => decodeKey("short")).toThrow();
  });
});
