import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  timingSafeEqual
} from "node:crypto";
import { requiredEnv } from "./env.js";

export type EncryptedValue = {
  v: 1;
  alg: "A256GCM";
  iv: string;
  tag: string;
  data: string;
};

export function decodeKey(value: string): Buffer {
  const key = /^[a-f0-9]{64}$/i.test(value)
    ? Buffer.from(value, "hex")
    : Buffer.from(value, "base64");
  if (key.length !== 32) {
    throw new Error("Credential encryption key must contain exactly 32 bytes");
  }
  return key;
}

export function currentEncryptionKey(): Buffer {
  return decodeKey(requiredEnv("CREDENTIAL_ENCRYPTION_KEY"));
}

export function encryptSecret(
  plaintext: string,
  key = currentEncryptionKey()
): EncryptedValue {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const data = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final()
  ]);
  return {
    v: 1,
    alg: "A256GCM",
    iv: iv.toString("base64"),
    tag: cipher.getAuthTag().toString("base64"),
    data: data.toString("base64")
  };
}

export function decryptSecret(
  encrypted: EncryptedValue,
  key = currentEncryptionKey()
): string {
  if (encrypted.v !== 1 || encrypted.alg !== "A256GCM") {
    throw new Error("Unsupported credential ciphertext version");
  }
  const decipher = createDecipheriv(
    "aes-256-gcm",
    key,
    Buffer.from(encrypted.iv, "base64")
  );
  decipher.setAuthTag(Buffer.from(encrypted.tag, "base64"));
  return Buffer.concat([
    decipher.update(Buffer.from(encrypted.data, "base64")),
    decipher.final()
  ]).toString("utf8");
}

export function rotateSecret(
  encrypted: EncryptedValue,
  oldKey: Buffer,
  newKey: Buffer
): EncryptedValue {
  if (oldKey.length !== 32 || newKey.length !== 32) {
    throw new Error("Both rotation keys must contain exactly 32 bytes");
  }
  if (timingSafeEqual(oldKey, newKey)) {
    return encrypted;
  }
  return encryptSecret(decryptSecret(encrypted, oldKey), newKey);
}
