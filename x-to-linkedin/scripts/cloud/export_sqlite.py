"""Create an encrypted, deterministic migration snapshot from the live SQLite DB."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from Cryptodome.Cipher import AES


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "x_to_linkedin.db"
ARTIFACT_ROOT = ROOT / "migration-artifacts"
SECRET_FILE = ARTIFACT_ROOT / "cloud-secrets.env"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        )
        digest.update(b"\n")
    return digest.hexdigest()


def load_json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def load_or_create_secrets() -> dict[str, str]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    values: dict[str, str] = {}
    if SECRET_FILE.exists():
        for line in SECRET_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    values.setdefault(
        "CREDENTIAL_ENCRYPTION_KEY",
        base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
    )
    values.setdefault("TELEGRAM_WEBHOOK_SECRET", secrets.token_urlsafe(32))
    values.setdefault("DISPATCH_SECRET", secrets.token_urlsafe(32))
    values.setdefault("WORKER_SECRET", secrets.token_urlsafe(32))
    values.setdefault("BACKUP_PASSPHRASE", secrets.token_urlsafe(48))
    SECRET_FILE.write_text(
        "\n".join(f"{key}={value}" for key, value in sorted(values.items())) + "\n",
        encoding="utf-8",
    )
    return values


def encrypt_secret(plaintext: str, key: bytes) -> dict[str, Any]:
    nonce = secrets.token_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
    data, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
    return {
        "v": 1,
        "alg": "A256GCM",
        "iv": base64.b64encode(nonce).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
        "data": base64.b64encode(data).decode("ascii"),
    }


def snapshot_database(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cursor = connection.execute(f'SELECT * FROM "{table}" ORDER BY id')
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def normalize_media(value: Any) -> str:
    media = str(value or "none")
    if media in {"generate", "paper_image", "auto"}:
        return "none"
    return media if media in {"none", "image", "video", "document"} else "none"


def export_posts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows(connection, "scheduled_posts"):
        status = str(row.get("status") or "pending")
        scheduled_at = row.get("scheduled_at")
        output.append(
            {
                "id": row["id"],
                "tweet_url": row.get("tweet_url") or "",
                "tweet_text": row.get("tweet_text") or "",
                "tweet_author": row.get("tweet_author") or "",
                "linkedin_text": row.get("linkedin_text") or "",
                "image_urls": load_json(row.get("image_urls"), []),
                "scheduled_at": scheduled_at,
                "approved_at": None,
                "publish_at": scheduled_at if status in {"scheduled", "publishing"} else None,
                "publishing_at": None,
                "published_at": row.get("published_at"),
                "status": status,
                "linkedin_post_id": row.get("linkedin_post_id"),
                "error_message": row.get("error_message"),
                "created_at": row.get("created_at"),
                "use_first_image": bool(row.get("use_first_image")),
                "media_type": normalize_media(row.get("media_type")),
                "pdf_url": row.get("pdf_url"),
                "document_title": row.get("document_title") or "Documento",
                "source": row.get("source") or "manual",
                "manual_edited_at": row.get("manual_edited_at"),
                "manual_edited_via": row.get("manual_edited_via"),
                "editorial_revision_notes": row.get("editorial_revision_notes"),
                "generated_image_path": None,
                "li_likes": row.get("li_likes"),
                "li_comments": row.get("li_comments"),
                "li_impressions": row.get("li_impressions"),
                "li_clicks": row.get("li_clicks"),
                "li_shares": row.get("li_shares"),
                "metrics_updated_at": row.get("metrics_updated_at"),
                "source_metadata": {},
                "verification_metadata": {},
                "version": 1,
            }
        )
    return output


def export_tokens(connection: sqlite3.Connection, key: bytes) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows(connection, "linkedin_tokens"):
        access_token = str(row.pop("access_token", "") or "")
        refresh_token = str(row.pop("refresh_token", "") or "")
        output.append(
            {
                "id": row["id"],
                "access_token_cipher": encrypt_secret(access_token, key),
                "refresh_token_cipher": (
                    encrypt_secret(refresh_token, key) if refresh_token else None
                ),
                "cipher_version": 1,
                "person_urn": row.get("person_urn") or "",
                "person_name": row.get("person_name") or "",
                "person_picture": row.get("person_picture") or "",
                "expires_at": row.get("expires_at"),
                "refresh_token_expires_at": row.get("refresh_token_expires_at"),
                "created_at": row.get("created_at"),
            }
        )
    return output


def export_comments(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    output = rows(connection, "linkedin_comments")
    for row in output:
        row["owner_replied"] = bool(row.get("owner_replied"))
        row["raw_payload"] = load_json(row.get("raw_payload"), None)
    return output


def export_settings(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows(connection, "app_settings")


def export_likes(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows(connection, "x_liked_tweets")


def write_jsonl(path: Path, data: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in data:
            handle.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            )
            handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    database = args.database.resolve()
    if not database.exists() or not database.is_file():
        raise SystemExit(f"SQLite database not found: {database}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or ARTIFACT_ROOT / f"snapshot-{timestamp}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    temp_snapshot = output / ".sqlite-consistent-snapshot.db"
    snapshot_database(database, temp_snapshot)
    database_hash = sha256_file(temp_snapshot)

    secret_values = load_or_create_secrets()
    key = base64.b64decode(secret_values["CREDENTIAL_ENCRYPTION_KEY"])
    if len(key) != 32:
        raise SystemExit("CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes")

    connection = sqlite3.connect(f"file:{temp_snapshot.as_posix()}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        datasets = {
            "settings": export_settings(connection),
            "linkedin_tokens": export_tokens(connection, key),
            "posts": export_posts(connection),
            "x_liked_tweets": export_likes(connection),
            "linkedin_comments": export_comments(connection),
        }
    finally:
        connection.close()
        temp_snapshot.unlink(missing_ok=True)

    file_manifest: dict[str, Any] = {}
    for name, data in datasets.items():
        path = output / f"{name}.jsonl"
        write_jsonl(path, data)
        file_manifest[path.name] = {
            "rows": len(data),
            "sha256": sha256_file(path),
            "canonical_sha256": canonical_hash(data),
        }

    posts = datasets["posts"]
    manifest = {
        "format_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_database": database.name,
        "source_database_bytes": database.stat().st_size,
        "source_database_snapshot_sha256": database_hash,
        "files": file_manifest,
        "post_status_counts": {
            status: sum(1 for post in posts if post["status"] == status)
            for status in sorted({str(post["status"]) for post in posts})
        },
        "post_source_counts": {
            source: sum(1 for post in posts if post["source"] == source)
            for source in sorted({str(post["source"]) for post in posts})
        },
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "artifact": str(output),
                "manifest": str(manifest_path),
                "counts": {name: len(data) for name, data in datasets.items()},
                "secret_file": str(SECRET_FILE),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
