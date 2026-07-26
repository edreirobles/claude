import { db } from "../../cloud/src/db.js";
import { requiredEnv } from "../../cloud/src/env.js";

const sql = db();
const appOrigin = requiredEnv("APP_ORIGIN").replace(/\/+$/, "");
const dispatchUrl = `${appOrigin}/api/dispatch`;
const dispatchSecret = requiredEnv("DISPATCH_SECRET");

await sql.begin(async (transaction) => {
  await transaction`
    delete from vault.secrets
    where name in ('x2li_dispatch_url', 'x2li_dispatch_secret')
  `;
  await transaction`
    select vault.create_secret(
      ${dispatchUrl},
      'x2li_dispatch_url',
      'Netlify dispatcher endpoint for x-to-linkedin'
    )
  `;
  await transaction`
    select vault.create_secret(
      ${dispatchSecret},
      'x2li_dispatch_secret',
      'Shared dispatcher secret for x-to-linkedin'
    )
  `;
  await transaction`
    select cron.unschedule(jobid)
    from cron.job where jobname = 'x2li-dispatch'
  `;
  await transaction`
    select cron.schedule(
      'x2li-dispatch',
      '* * * * *',
      'select app.dispatch_due_jobs()'
    )
  `;
  await transaction`select app.schedule_periodic_jobs()`;
});

const checks = await sql<
  Array<{
    cron_jobs: number;
    anon_tables: number;
    authenticated_tables: number;
  }>
>`
  select
    (select count(*)::integer from cron.job where jobname = 'x2li-dispatch') as cron_jobs,
    (select count(*)::integer
      from information_schema.role_table_grants
      where table_schema = 'app' and grantee = 'anon') as anon_tables,
    (select count(*)::integer
      from information_schema.role_table_grants
      where table_schema = 'app' and grantee = 'authenticated') as authenticated_tables
`;
const check = checks[0]!;
if (check.cron_jobs !== 1 || check.anon_tables || check.authenticated_tables) {
  throw new Error("Cloud database security or cron verification failed");
}
process.stdout.write(
  JSON.stringify({
    configured: true,
    cron_jobs: check.cron_jobs,
    app_schema_exposed_to_anon: false,
    app_schema_exposed_to_authenticated: false
  }) + "\n"
);
