import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { db } from "../../cloud/src/db.js";

type Manifest = {
  files: Record<string, { rows: number }>;
  post_status_counts: Record<string, number>;
  post_source_counts: Record<string, number>;
};

const directoryArg = process.argv[2] ?? process.env.MIGRATION_ARTIFACT_DIR;
if (!directoryArg) throw new Error("Pass the snapshot directory or set MIGRATION_ARTIFACT_DIR");
const directory = resolve(directoryArg);
const manifest = JSON.parse(
  await readFile(resolve(directory, "manifest.json"), "utf8")
) as Manifest;
const sql = db();
const tableMap = {
  settings: "settings",
  linkedin_tokens: "linkedin_tokens",
  posts: "posts",
  x_liked_tweets: "x_liked_tweets",
  linkedin_comments: "linkedin_comments"
} as const;
const counts: Record<string, number> = {};
for (const [fileName, table] of Object.entries(tableMap)) {
  const rows = await sql.unsafe<Array<{ count: number }>>(
    `select count(*)::integer as count from app.${table}`
  );
  counts[fileName] = Number(rows[0]?.count ?? 0);
}
const statuses = await sql<Array<{ status: string; count: number }>>`
  select status, count(*)::integer as count from app.posts group by status
`;
const sources = await sql<Array<{ source: string; count: number }>>`
  select source, count(*)::integer as count from app.posts group by source
`;
const actualStatus = Object.fromEntries(statuses.map((row) => [row.status, row.count]));
const actualSource = Object.fromEntries(sources.map((row) => [row.source, row.count]));
const expectedCounts = Object.fromEntries(
  Object.entries(tableMap).map(([name]) => [
    name,
    manifest.files[`${name}.jsonl`]?.rows ?? 0
  ])
);
const failures: string[] = [];
for (const [name, expected] of Object.entries(expectedCounts)) {
  if (counts[name] !== expected) failures.push(`${name}: ${counts[name]} != ${expected}`);
}
if (JSON.stringify(actualStatus) !== JSON.stringify(manifest.post_status_counts)) {
  failures.push("post status counts differ");
}
if (JSON.stringify(actualSource) !== JSON.stringify(manifest.post_source_counts)) {
  failures.push("post source counts differ");
}
process.stdout.write(
  JSON.stringify(
    {
      ok: failures.length === 0,
      expected_counts: expectedCounts,
      actual_counts: counts,
      expected_status: manifest.post_status_counts,
      actual_status: actualStatus,
      expected_source: manifest.post_source_counts,
      actual_source: actualSource,
      failures
    },
    null,
    2
  ) + "\n"
);
if (failures.length) process.exitCode = 1;
