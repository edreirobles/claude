from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.database import Base
from app.logging_security import RedactingFormatter, redact_sensitive_text
from app.models import ScheduledPost
from app.services import editorial_radar, scheduler_service, telegram_bot


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append((text, kwargs))
        return self


class FakeQuery:
    def __init__(self) -> None:
        self.message = FakeMessage()
        self.markup_edits = 0
        self.answer_count = 0
        self.data = ""
        self.from_user = type("User", (), {"id": 1})()

    async def answer(self):
        self.answer_count += 1

    async def edit_message_reply_markup(self, *args, **kwargs):
        self.markup_edits += 1


class FrozenDateTime(datetime):
    current = datetime(2026, 7, 15, 12, 0)

    @classmethod
    def utcnow(cls):
        return cls.current


class Phase0CharacterizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "characterization.db"
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}"
        )
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def create_post(self, **overrides) -> int:
        values = {
            "tweet_url": "https://example.com/source",
            "tweet_text": "Source summary",
            "tweet_author": "Source",
            "linkedin_text": "Draft",
            "image_urls": [],
            "status": "approval_pending",
            "media_type": "none",
            "source": "radar",
        }
        values.update(overrides)
        async with self.Session() as session:
            post = ScheduledPost(**values)
            session.add(post)
            await session.commit()
            await session.refresh(post)
            return post.id

    async def load_post(self, post_id: int) -> ScheduledPost:
        async with self.Session() as session:
            post = await session.get(ScheduledPost, post_id)
            assert post is not None
            session.expunge(post)
            return post

    async def test_approval_runs_30_minutes_later_across_day_and_dst_boundary(self):
        scenarios = (
            datetime(2026, 7, 15, 23, 45),
            datetime(2022, 10, 30, 6, 45),
        )
        for approved_at in scenarios:
            with self.subTest(approved_at=approved_at.isoformat()):
                post_id = await self.create_post(
                    media_type="generate",
                    generated_image_path="legacy/generated.jpg",
                )
                FrozenDateTime.current = approved_at
                query = FakeQuery()
                with (
                    patch.object(database, "AsyncSessionLocal", self.Session),
                    patch.object(
                        scheduler_service, "schedule_post"
                    ) as schedule_post_mock,
                    patch.object(telegram_bot, "datetime", FrozenDateTime),
                    patch.object(
                        telegram_bot.settings,
                        "editorial_radar_publish_delay_minutes",
                        30,
                    ),
                ):
                    await telegram_bot._do_approve_radar(query, post_id)

                post = await self.load_post(post_id)
                expected = approved_at + timedelta(minutes=30)
                self.assertEqual(post.status, "scheduled")
                self.assertEqual(post.scheduled_at, expected)
                self.assertEqual(post.media_type, "none")
                self.assertIsNone(post.generated_image_path)
                schedule_post_mock.assert_called_once_with(post_id, expected)

    async def test_repeated_approval_does_not_schedule_twice(self):
        post_id = await self.create_post()
        FrozenDateTime.current = datetime(2026, 7, 15, 10, 0)
        first_query = FakeQuery()
        second_query = FakeQuery()
        with (
            patch.object(database, "AsyncSessionLocal", self.Session),
            patch.object(scheduler_service, "schedule_post") as schedule_post_mock,
            patch.object(telegram_bot, "datetime", FrozenDateTime),
            patch.object(
                telegram_bot.settings,
                "editorial_radar_publish_delay_minutes",
                30,
            ),
        ):
            await telegram_bot._do_approve_radar(first_query, post_id)
            FrozenDateTime.current = datetime(2026, 7, 15, 10, 5)
            await telegram_bot._do_approve_radar(second_query, post_id)

        post = await self.load_post(post_id)
        self.assertEqual(post.scheduled_at, datetime(2026, 7, 15, 10, 30))
        schedule_post_mock.assert_called_once()
        self.assertIn("ya no", second_query.message.replies[-1][0].lower())

    async def test_radar_approval_button_dispatches_to_approval_handler(self):
        query = FakeQuery()
        query.data = "radar_approve:42"
        update = type("Update", (), {"callback_query": query})()
        approve_mock = AsyncMock()
        with (
            patch.object(telegram_bot, "_do_approve_radar", approve_mock),
            patch.object(telegram_bot.settings, "telegram_user_id", 0),
        ):
            await telegram_bot.handle_callback(update, None)

        self.assertEqual(query.answer_count, 1)
        approve_mock.assert_awaited_once_with(query, 42)

    async def test_cancel_pending_approval(self):
        post_id = await self.create_post()
        query = FakeQuery()
        with (
            patch.object(database, "AsyncSessionLocal", self.Session),
            patch.object(
                scheduler_service, "cancel_scheduled_post"
            ) as cancel_scheduled_post_mock,
        ):
            await telegram_bot._do_cancel(query, post_id)

        post = await self.load_post(post_id)
        self.assertEqual(post.status, "cancelled")
        cancel_scheduled_post_mock.assert_called_once_with(post_id)

    def test_revision_notes_accumulate_without_duplicates(self):
        notes = telegram_bot._append_revision_note(None, "Hazlo mas directo")
        notes = telegram_bot._append_revision_note(notes, "Agrega un ejemplo")
        notes = telegram_bot._append_revision_note(notes, "hazlo mas directo")
        self.assertEqual(notes, "Hazlo mas directo\nAgrega un ejemplo")

    async def test_radar_approval_does_not_expire(self):
        post_id = await self.create_post(
            scheduled_at=datetime.utcnow() - timedelta(days=30)
        )
        verify_mock = AsyncMock()
        linkedin_mock = AsyncMock()
        with (
            patch.object(database, "AsyncSessionLocal", self.Session),
            patch(
                "app.services.post_verifier.verify_scheduled_post", verify_mock
            ),
            patch(
                "app.services.linkedin_auth.get_linkedin_client_from_db",
                linkedin_mock,
            ),
        ):
            await scheduler_service.execute_scheduled_post(post_id)

        post = await self.load_post(post_id)
        self.assertEqual(post.status, "approval_pending")
        verify_mock.assert_not_awaited()
        linkedin_mock.assert_not_awaited()

    async def test_paused_posts_are_not_rehydrated(self):
        await self.create_post(
            status="paused",
            scheduled_at=datetime.utcnow() + timedelta(hours=1),
            source="manual",
        )
        with (
            patch.object(database, "AsyncSessionLocal", self.Session),
            patch.object(scheduler_service, "schedule_post") as schedule_post_mock,
        ):
            await scheduler_service.rehydrate_scheduled_posts()
        schedule_post_mock.assert_not_called()

    async def test_radar_discards_generated_image_fallback(self):
        post_id = await self.create_post(status="radar_slot")
        candidate = editorial_radar.RadarCandidate(
            url="https://example.com/tool",
            title="Useful AI tool",
            summary="A focused tool",
            source_name="Example",
            source_domain="example.com",
            kind="tool",
        )
        decision = editorial_radar.RadarDecision(
            candidate=candidate,
            reason="Useful now",
            intent="presentar",
            angle="practical",
        )
        payload = {
            "tweet_url": candidate.url,
            "tweet_text": candidate.summary,
            "tweet_author": candidate.source_name,
            "linkedin_text": "Prueba esta herramienta.",
            "image_urls": [],
            "media_type": "generate",
        }
        with (
            patch.object(editorial_radar, "AsyncSessionLocal", self.Session),
            patch.object(
                editorial_radar,
                "get_text_generation_config_error",
                return_value=None,
            ),
            patch.object(
                editorial_radar,
                "_load_custom_prompt",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                editorial_radar,
                "get_editorial_learning_profile",
                new=AsyncMock(return_value=""),
            ),
            patch.object(
                editorial_radar,
                "collect_radar_candidates",
                new=AsyncMock(return_value=[candidate]),
            ),
            patch.object(
                editorial_radar,
                "rank_radar_candidates",
                new=AsyncMock(return_value=[decision]),
            ),
            patch.object(
                editorial_radar,
                "_build_post_payload_from_source",
                new=AsyncMock(return_value=payload),
            ),
        ):
            result = await editorial_radar.prepare_radar_post(post_id)

        post = await self.load_post(post_id)
        self.assertTrue(result["prepared"])
        self.assertEqual(post.status, "approval_pending")
        self.assertEqual(post.media_type, "none")
        self.assertEqual(post.image_urls, [])
        self.assertIsNone(post.generated_image_path)


class Phase0SecurityAndSnapshotTests(unittest.TestCase):
    def test_log_redaction_covers_sensitive_shapes(self):
        samples = (
            "Authorization: Bearer bearer-value-123",
            "Cookie: li_at=session-value; JSESSIONID=ajax-value",
            "LINKEDIN_CLIENT_SECRET=client-secret-value",
            "DATABASE_URL=postgresql://owner:password@example.com/db",
            "123456789:" + "telegram-token-value-with-enough-characters",
        )
        for sample in samples:
            with self.subTest(sample=sample.split(":", 1)[0]):
                redacted = redact_sensitive_text(sample)
                self.assertIn("[REDACTED]", redacted)
                self.assertNotIn("value", redacted)
                self.assertNotIn("password", redacted)

        formatter = RedactingFormatter("%(levelname)s %(message)s")
        record = __import__("logging").LogRecord(
            "test",
            20,
            __file__,
            1,
            "OPENAI_API_KEY=top-secret-value",
            (),
            None,
        )
        self.assertNotIn("top-secret-value", formatter.format(record))

    def test_phase0_snapshot_totals_are_consistent(self):
        fixture = (
            Path(__file__).parent / "fixtures" / "phase0_snapshot.json"
        )
        snapshot = json.loads(fixture.read_text(encoding="utf-8"))
        total_posts = snapshot["tables"]["scheduled_posts"]
        self.assertEqual(
            sum(snapshot["scheduled_posts_by_status"].values()), total_posts
        )
        self.assertEqual(
            sum(snapshot["scheduled_posts_by_source"].values()), total_posts
        )
        self.assertEqual(snapshot["tables"]["linkedin_comments"], 170)
        self.assertEqual(snapshot["tables"]["x_liked_tweets"], 132)


if __name__ == "__main__":
    unittest.main()
