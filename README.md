# AIMIS — AI Mock Interview System

A web system where college students and fresh graduates practice **job interviews for their target career** by
voice, focused on communication and behavioral skills. An on-screen interviewer (AIMIS Bot) asks questions out loud,
the student answers by speaking, the interviewer responds and may ask a follow-up, and AIMIS scores what was said
and how it was said, then gives specific feedback.

Capstone project of Group 6, First City Providential College.

## Features

- **Career goal:** after creating an account the student picks the job they are preparing for (e.g. IT professional);
  it can be changed anytime. Edit the list in `careers.py`.
- **Conversational interview (no preset questions):** 8 communication/behavioral skills × 3 levels. AIMIS Bot opens
  by asking the student's name and about themselves; after each answer it replies, then asks either ONE follow-up
  (vague answer, no example or no result) or the next question, written live from the conversation, the target
  job, the skill and the level. Approved bank questions are the backup when the AI is unavailable. Questions read
  aloud, spoken answers, live transcript (Chrome/Edge), camera face check before starting.
- **Scoring (rubric v2, all in `scoring.py`):** two separate scores, every criterion 0–100 with 5 described levels.
  - **Answer Effectiveness** (what was said, would it work in a real interview): relevance, directness,
    structure (STAR), specific evidence, 25% each.
  - **Communication Delivery** (how it was said): 60% verbal (fluency, speech clarity, vocal confidence, grammar)
    + 40% nonverbal (eye contact 50%, facial expression 25%, gestures 25%; MediaPipe in the browser).
  - **Interview readiness** = 60% Answer Effectiveness + 40% Communication Delivery, plus a performance profile
    (e.g. "Effective answers, delivery needs polish"). Missing parts (no camera) are left out and the rest rescaled.
- **Specific feedback:** every point names the answer, quotes the student, and gives a fix and an example answer;
  sub-skill labels (critical thinking, problem solving, …) on every answer; comparison with earlier interviews.
- **AIMIS Coach:** a chatbot that answers questions about the student's own interviews using RAG
  (local Ollama models; understands English, Filipino and Taglish questions, always replies in English).
- **Dashboard:** skill rings, sub-skill trend lines, history.
- **Admin panel:** overview (incl. sub-skills across all students), users, interview records + CSV,
  AI-written questions with admin review, **validation** (human evaluators vs AI).
- **Privacy & security:** consent per interview, encrypted recordings, automatic deletion after N days,
  My data page (delete interviews / account), CSRF tokens, login lockout, secure cookies.
- **Works when Gemini fails:** scoring falls back to Ollama and speech-to-text to Whisper; fully offline mode available.

## Setup (Windows)

Requirements: Python 3.11+, MySQL (with the AIMIS database imported), [Ollama](https://ollama.com).

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          (then fill in .env)
ollama pull gemma3:4b
ollama pull nomic-embed-text
python download_mediapipe.py    (camera works without internet)
python check_setup.py --fix     (checks everything and adds missing database tables/columns)
python app.py
```

Open http://127.0.0.1:5000. Make yourself admin in MySQL:
`UPDATE users SET role = 'admin' WHERE email = 'your@email.com';`

Optional:
- `pip install faster-whisper` — offline speech-to-text backup
- `python seed_demo.py` — demo account `demo@aimis.local` / `demo1234` with 4 scored interviews
- `python rag_index.py` — rebuild the chatbot's knowledge base for all interviews

## Settings (.env)

See `.env.example` for every setting. The important ones:

| Setting | What it does |
|---|---|
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL` | Google Gemini for speech-to-text, scoring, question writing |
| `AUDIO_ENCRYPTION_KEY` | Encrypts voice recordings. Each PC keeps its own; never change it once recordings exist |
| `EVAL_PROVIDER=ollama`, `TRANSCRIBE_PROVIDER=whisper` | Fully offline mode (nothing sent to Google) |
| `AI_FALLBACK=0` | Turn off the automatic local backups |
| `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL` | Local models for the chatbot and backup scoring |
| `RECORDING_RETENTION_DAYS` | Recordings older than this are deleted automatically (default 30) |
| `MAIL_USERNAME`, `MAIL_PASSWORD` | Gmail App Password for Forgot password emails |
| `ADAPTIVE_INTERVIEW=0` | Fixed question list instead of the conversation (default: conversation) |
| `FLASK_DEBUG=1` | Debug mode, only on your own laptop |

Never push `.env`, `uploads/` or CSV exports with names to GitHub.

## Project structure

| File | Purpose |
|---|---|
| `app.py` | Flask app: accounts, interview flow, processing, scoring formula, reports, dashboard |
| `ai_service.py` | Gemini prompts and calls (transcription, evaluation, question writing) with automatic backups |
| `offline_ai.py` | Local backups: Whisper speech-to-text, Ollama scoring |
| `speech_service.py` | Pauses, pitch, volume and confidence from the audio (librosa) |
| `nlp_service.py` | Text statistics (NLTK) |
| `personal_feedback.py` | Per-answer feedback, sub-skill labels, feedback items, progress, sub-skill trends |
| `rag.py`, `chatbot.py`, `rag_index.py` | AIMIS Coach: RAG indexing, retrieval, generation, chat routes |
| `admin.py` | Admin panel |
| `validation.py` | Human evaluator ratings and AI-vs-human agreement statistics |
| `my_data.py` | My data page, data deletion, automatic recording deletion |
| `security.py` | CSRF, login lockout, cookies, security headers, account checks |
| `password_reset.py` | Forgot password by email |
| `check_setup.py` | Setup check and database fixer |
| `seed_demo.py` | Demo account for presentations |
| `templates/`, `static/` | Pages, styles, robot, MediaPipe files |
| `database/` | SQL for the tables added during development (also applied by `check_setup.py --fix`) |

## Troubleshooting

| Problem | Fix |
|---|---|
| Something is missing or a column error (1054) | `python check_setup.py --fix` |
| "Gemini's free limit has been reached" | Wait for the daily reset, or let the Ollama backup score it (Ollama must be running) |
| Chatbot says the AI isn't running | Open Ollama; check the models with `ollama list` |
| MySQL 2002 / 2013 | Start MySQL; if a table is damaged: `CHECK TABLE name; REPAIR TABLE name;` |
| Live transcript doesn't appear | Use Chrome or Edge |
| Locked out after wrong passwords | Wait 15 minutes or restart the app |
