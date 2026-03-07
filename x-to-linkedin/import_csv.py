"""
Recupera publicaciones desde el CSV exportado por la app.
Uso:
    python import_csv.py publicaciones.csv
    python import_csv.py publicaciones_2025-01-01_hoy.csv
"""
import csv
import sys
import asyncio
from datetime import datetime
from pathlib import Path

# Ajustar path para importar la app
sys.path.insert(0, str(Path(__file__).parent))

from app.database import AsyncSessionLocal, init_db
from app.models import ScheduledPost


def _parse_dt(val: str):
    if not val or val.strip() == '':
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f'):
        try:
            return datetime.strptime(val.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_bool(val: str) -> bool:
    return val.strip().lower() in ('true', '1', 'yes', 'si', 'sí')


async def import_csv(csv_path: str):
    await init_db()

    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("El CSV está vacío.")
        return

    print(f"Encontradas {len(rows)} filas en el CSV.")

    inserted = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        for row in rows:
            post = ScheduledPost(
                tweet_url=row.get('tweet_url', ''),
                tweet_text=row.get('tweet_text', ''),
                tweet_author=row.get('tweet_author', ''),
                linkedin_text=row.get('linkedin_text', ''),
                image_urls=[],
                status=row.get('status', 'published'),
                source=row.get('source', 'manual'),
                scheduled_at=_parse_dt(row.get('scheduled_at', '')),
                published_at=_parse_dt(row.get('published_at', '')),
                created_at=_parse_dt(row.get('created_at', '')) or datetime.utcnow(),
                linkedin_post_id=row.get('linkedin_post_id') or None,
                media_type=row.get('media_type', 'auto'),
                use_first_image=_parse_bool(row.get('use_first_image', 'true')),
                pdf_url=row.get('pdf_url') or None,
                document_title=row.get('document_title') or 'Documento',
                error_message=row.get('error_message') or None,
            )
            db.add(post)
            inserted += 1

        await db.commit()

    print(f"✓ Importados: {inserted} posts")
    print(f"  Saltados:   {skipped}")
    print("Listo. Reinicia la app y recarga el historial.")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python import_csv.py <archivo.csv>")
        sys.exit(1)
    asyncio.run(import_csv(sys.argv[1]))
