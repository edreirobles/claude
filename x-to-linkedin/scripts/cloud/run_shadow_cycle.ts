import { db } from "../../cloud/src/db.js";
import { switches } from "../../cloud/src/env.js";
import { maintainRadarSchedule } from "../../cloud/src/radar.js";
import { sendApprovalCard } from "../../cloud/src/telegram.js";

if (switches.publishingEnabled() || switches.telegramSendEnabled()) {
  throw new Error("Shadow cycle requires publishing and Telegram sending to be disabled");
}
const startedAt = new Date().toISOString();
const schedule = switches.radarEnabled()
  ? await maintainRadarSchedule()
  : { created: 0, queued: 0 };
const approvals = await db()<Array<{ id: number; version: number }>>`
  select id, version
  from app.posts where status = 'approval_pending'
  order by id desc limit 1
`;
if (approvals[0]) {
  await sendApprovalCard(approvals[0].id, "shadow validation", approvals[0].version);
}
const unsafeEffects = await db()<Array<{ count: number }>>`
  select count(*)::integer as count
  from app.external_effects
  where created_at >= ${startedAt}::timestamptz
    and effect_type in ('linkedin_post', 'linkedin_comment', 'telegram_message')
    and status = 'succeeded'
`;
const generatedMedia = await db()<Array<{ count: number }>>`
  select count(*)::integer as count
  from app.posts
  where status in ('pending', 'radar_slot', 'approval_pending', 'scheduled')
    and generated_image_path is not null
`;
if (unsafeEffects[0]!.count || generatedMedia[0]!.count) {
  throw new Error("Shadow safety verification failed");
}
process.stdout.write(
  JSON.stringify({
    shadow_ok: true,
    radar: schedule,
    approval_payload_captured: Boolean(approvals[0]),
    successful_external_effects: 0,
    active_generated_images: 0
  }) + "\n"
);
