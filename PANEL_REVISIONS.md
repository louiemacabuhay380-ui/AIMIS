# AIMIS panel revisions: system changes (comments 5, 6, 8, 10, 11, 12)

## How to install

1. **Back up first.** Copy your whole AIMIS folder and export the database in SQLyog.
2. Copy every file from this package into your AIMIS folder, replacing the old ones.
   New files: `scoring.py`, `careers.py`, `templates/career.html`, `database/block10_panel_revisions.sql`.
3. Update the database (pick one):
   - `python check_setup.py --fix`, or
   - run `database/block10_panel_revisions.sql` in SQLyog.
4. Run `python app.py` as usual. No new packages are needed.

**Existing students:** the next time they log in, AIMIS asks for their career goal.
**Old reports:** they still open and show the old scores. Each one has a "Re-score with the new rubric" button,
which uses 1 Gemini request and does not record the answers again.

**Database warning:** the backup `aimisbackup.sql` has 85 `behavior_analysis` rows and 84 `nlp_analysis` rows that
belong to answers that no longer exist (response IDs 52–136). If you restore that backup on another PC, saving a new
answer crashes with "Duplicate entry ... for key uq_behavior_response". This also happens with the old code.
Fix after restoring (deletes only the orphaned rows):

```sql
DELETE b FROM behavior_analysis b LEFT JOIN responses r ON r.response_id = b.response_id WHERE r.response_id IS NULL;
DELETE n FROM nlp_analysis n LEFT JOIN responses r ON r.response_id = n.response_id WHERE r.response_id IS NULL;
```

## What changed, by panel comment

### 5–6. Specialization by career goal

- After creating an account, the student picks a career goal: IT professional, Customer service / BPO,
  Business and office administration, Accounting and finance, Sales and marketing, Teaching and education,
  Hospitality and tourism, Healthcare, Criminology and public safety, Engineering and technical work,
  or something else typed in. They can change it anytime. The list is in `careers.py`.
- Every question is set in that job. For example, IT professional + Communication: "Tell me about a time you had
  to explain a technical problem to someone who isn't technical." The questions still test the chosen
  communication/behavioral skill, never technical knowledge, so the title still fits.
- Each interview remembers the career goal it was for.

### 8. A conversation, not preset questions

There is **no question list prepared before the interview**. It runs like a real interview:

1. **First interview ever:** AIMIS Bot greets the student and asks: "To start, may I know your name, and can you
   tell me a little about yourself?"
   **Every later interview:** it doesn't ask again. It says "Welcome back, Juan!" and starts with a first question
   the AI writes for that student, which can connect to what they said in their introduction (e.g. their OJT).
2. After every answer, **one Gemini call** does all of this at once:
   - transcribes the answer and rates fluency and clarity,
   - writes a short reply that shows the robot listened ("Nice to meet you, Juan. So you did your OJT in IT
     support."), with no grading,
   - decides what comes next. That is either **one follow-up** about this answer (only when it was vague, had no
     real example, or no result), or the **next main question**. The next question is written from the
     conversation so far, the target job, the skill and the level, and it never repeats an earlier question.
3. The robot asks it out loud, and the conversation continues until the chosen number of main questions
   (including the introduction) is reached. Follow-ups don't count toward that number. There is no follow-up on
   the introduction, and a follow-up never gets its own follow-up.

Notes:
- It uses the same number of Gemini calls as before. Before, each answer was transcribed after the interview;
  now that same call also writes the reply and the next question.
- The student waits a few seconds while the robot "thinks". If that step fails or takes over 40 seconds, AIMIS tries
  again with a quick text-only request to write the next question from the conversation (Gemini, then Ollama).
  Only if both fail does it take a question from the approved bank, so the interview never stops.
- The terminal shows where every question came from, so you can check during testing:
  `[AIMIS Bot] next question written live from the conversation`, `[AIMIS Bot] follow-up question written live`,
  or `[AIMIS Bot] ... using a bank question` with the reason (for example, Gemini's free limit was reached).
- The introduction is scored too. For it, "structure" means a clear order: who they are, relevant background,
  and why this job.
- The report labels the questions "Introduction" and "Follow-up on Q2".
- Privacy: questions written during the interview can refer to what the student said, so admins never see their
  text. They are deleted when the student deletes their data.
- The admin question bank is now only the backup. Admins can still generate and review bank questions,
  including for a specific job.

### 10–12. Two kinds of performance, clear weights, defined parameters

Everything is defined in one file, `scoring.py`. The AI prompt, the human evaluators' rubric, the report page
and the chatbot all read from it. Each criterion is scored 0–100 using five described levels
(100 / 75 / 50 / 25 / 0). The AI and the human evaluators use the same level descriptions.

**Interview Readiness = 60% Answer Effectiveness + 40% Communication Delivery**

| Score | Part | Criterion | Weight | How it is measured |
|---|---|---|---|---|
| **Answer Effectiveness** (what was said: would it work in a real interview?) | | Relevance | 25% | AI rubric: does it answer the exact question? |
| | | Directness | 25% | AI rubric: main point stated early, no rambling |
| | | Structure (STAR) | 25% | AI rubric: situation, action and result |
| | | Specific evidence | 25% | AI rubric: real example with concrete details |
| **Communication Delivery** (how it was said: effective communicator) | Verbal 60% | Fluency | 25% | AI rating of the recording |
| | | Speech clarity | 25% | AI rating of the recording (accent not penalized) |
| | | Vocal confidence | 25% | librosa: pauses, pitch variation, volume steadiness, fillers per minute |
| | | Grammar | 25% | AI rubric on the transcript |
| | Nonverbal 40% | Eye contact | 50% | MediaPipe: % of frames facing the camera (≤25° turn/tilt), eyes not looking away |
| | | Facial expression | 25% | MediaPipe: smiling ≥10% of the time = 100; frowning lowers it |
| | | Gestures | 25% | MediaPipe: open-hand gestures 10–60% of speaking time = 100; face touching lowers it |

- Score levels: Excellent 85–100, Proficient 70–84, Developing 50–69, Needs improvement 0–49.
  70 or more meets the standard.
- **Performance profile** (comment 10), from the two scores:
  - Interview-ready: both scores are 70 or more.
  - Effective answers, delivery needs polish: the answer works in a real interview, even if the delivery isn't polished.
  - Effective communicator, answers need substance: the student speaks well, but the answers are vague.
  - Keep practicing both.
- The AI is told directly that a short, plain answer that is direct, relevant and specific must score high on
  Answer Effectiveness, and that fluent but vague talk must score low on directness and specificity.
- The report shows both scores, the profile, the worked calculation with the student's own numbers, and the full
  rubric table. Each answer shows its own Answer and Delivery scores.
- Human evaluators (validation) now rate relevance, directness, structure, specific evidence and grammar.
  Pearson r is computed per criterion and for Answer Effectiveness.

## What to update in the paper

- **Chapter 1, SOP 2 / Scope:** add the career goal and the conversational interview (opens with the student's
  name and introduction; each next question and follow-up is generated from the conversation).
  Change "soft skills" wording to "communication and behavioral skills in the context of the user's target job".
- **Chapter 3, Step-by-Step Procedure:** replace "60% response quality, 25% speech performance and 15% behavioral
  performance" with the formula and table above. Describe the conversation loop: answer → transcription → reply → follow-up or next question.
- **Chapter 3, instrument for human raters:** the rubric criteria are now relevance, directness, structure (STAR),
  specific evidence and grammar (1–5).
- **Comment 2 (basis of the behavioral assessment):** the thresholds above (25°, 10% smiling, 10–60% gestures) and
  the weights (eye contact 50%, verbal 60 / nonverbal 40, answer 60 / delivery 40) still need a source.
  Cite 2021-or-later studies on nonverbal behavior and interviewer ratings, cite the MediaPipe documentation, and have
  your expert validators approve the numbers. If they want different numbers, change them in `scoring.py` (weights)
  and `templates/interview.html` (camera thresholds). Everything else updates by itself.

## When Gemini's limit is reached

- The daily limit resets at midnight Pacific time, about 4 PM Philippine time (3 PM during US daylight saving).
- When Gemini answers "limit reached" (429), AIMIS stops asking it: for 1 minute after a per-minute limit, and
  for 30 minutes after the daily limit. During that time it goes straight to the backups without any waiting:
  - Whisper (speech-to-text) and Ollama (replies, follow-ups, next questions, scoring), if installed and running;
  - otherwise approved bank questions during the interview.
- If the results page still can't finish, it says exactly why. For example: "offline speech-to-text isn't
  installed: pip install faster-whisper", or "open the Ollama app and press Try again". The answers are always
  saved, and the student can press Try again later.
- The offline model (gemma3:4b) scores one answer per request, because the whole interview in one request is too
  much for a small model (it skipped answers or ran out of memory). A 4-question interview takes about 1–2 minutes
  offline.
- For the defense PC: `pip install faster-whisper`, keep Ollama open with `gemma3:4b`, and run
  `python check_setup.py`.

## Settings (.env, optional)

- `LIVE_TIMEOUT_SECONDS=40` is the longest a student waits for the interviewer before the backup kicks in.
- `LIVE_THINKING=low` makes the live interviewer think more (better questions, but slower). The default is `minimal`.
- `ADAPTIVE_INTERVIEW=0` turns the conversation off and goes back to a fixed list of questions prepared at the start.
  Not recommended, because the panel asked for no preset questions.
- `QUESTION_MODE=bank` (only with `ADAPTIVE_INTERVIEW=0`) makes the fixed list use only approved bank questions.
