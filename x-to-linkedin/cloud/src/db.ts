import postgres, { type Sql } from "postgres";
import { requiredEnv } from "./env.js";

let client: Sql | undefined;

export function db(): Sql {
  if (!client) {
    client = postgres(requiredEnv("DATABASE_URL"), {
      max: 2,
      idle_timeout: 10,
      connect_timeout: 10,
      max_lifetime: 60 * 10,
      prepare: false,
      ssl: "require",
      onnotice: () => undefined
    });
  }
  return client;
}

export async function transaction<T>(work: (sql: Sql) => Promise<T>): Promise<T> {
  return db().begin(async (sql) => work(sql as unknown as Sql)) as Promise<T>;
}

export async function closeDbForTests(): Promise<void> {
  if (client) {
    await client.end({ timeout: 1 });
    client = undefined;
  }
}
