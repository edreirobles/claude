# CV Matcher

Tailors your CV to any job posting in seconds — honest, keyword-optimized, and downloaded as a professional PDF.

## What it does

1. **Paste a job URL or description** (LinkedIn, any job board, any language)
2. **Upload your CV** (PDF or Word)
3. **Download a tailored PDF** — rephrased to match the job, without inventing anything

## Quick start (local)

### Prerequisites

**macOS:**
```bash
brew install pango
```

**Ubuntu/Debian:**
```bash
sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libcairo2
```

### Run

```bash
git clone <repo-url>
cd cv-matcher
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
chmod +x start.sh
./start.sh
```

Open [http://localhost:8000](http://localhost:8000)

### Or with Docker

```bash
cp .env.example .env
# Edit .env
docker compose up --build
```

## Get an API key

1. Sign up at [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Add it to `.env` as `ANTHROPIC_API_KEY=sk-ant-...`

## Features

- Adapts CV language to match job requirements (no lies)
- Works with any language job description
- History of all generated CVs with download links
- Professional A4 PDF output
- Supports PDF and Word CVs
