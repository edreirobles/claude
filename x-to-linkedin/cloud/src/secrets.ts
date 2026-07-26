import { timingSafeEqual } from "node:crypto";
import { requiredEnv } from "./env.js";

export function secretMatches(actual: string | null, environmentName: string): boolean {
  if (!actual) return false;
  const expected = Buffer.from(requiredEnv(environmentName));
  const received = Buffer.from(actual);
  return expected.length === received.length && timingSafeEqual(expected, received);
}
