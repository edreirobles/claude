import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { encryptSecret } from "../../cloud/src/crypto.js";
import { closeDbForTests, db } from "../../cloud/src/db.js";

const capturedAt = new Date().toISOString();
const output = resolve(
  process.argv[2] ??
    `migration-artifacts/cloud-rollback-${capturedAt.replace(/[:.]/g, "")}.json.enc`
);
const sql = db();
const snapshot = {
  format_version: 1,
  captured_at: capturedAt,
  settings: await sql`select * from app.settings order by id`,
  linkedin_tokens: await sql`select * from app.linkedin_tokens order by id`,
  posts: await sql`select * from app.posts order by id`,
  x_liked_tweets: await sql`select * from app.x_liked_tweets order by id`,
  linkedin_comments: await sql`select * from app.linkedin_comments order by id`
};
const plaintext = JSON.stringify(snapshot);
const envelope = encryptSecret(plaintext);
await mkdir(dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(envelope), {
  encoding: "utf8",
  mode: 0o600
});
await closeDbForTests();

process.stdout.write(
  JSON.stringify({
    artifact: output,
    captured_at: capturedAt,
    ciphertext_sha256: createHash("sha256")
      .update(JSON.stringify(envelope))
      .digest("hex"),
    counts: {
      settings: snapshot.settings.length,
      linkedin_tokens: snapshot.linkedin_tokens.length,
      posts: snapshot.posts.length,
      x_liked_tweets: snapshot.x_liked_tweets.length,
      linkedin_comments: snapshot.linkedin_comments.length
    }
  }) + "\n"
);
