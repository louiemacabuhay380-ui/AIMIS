# AIMIS panel revisions: system changes (comments 5, 6, 8, 10, 11, 12)

## How to install (SQLite: no XAMPP)

AIMIS now uses **SQLite** instead of XAMPP / MySQL (adviser's request). The whole database is one file, `aimis.db`,
in the AIMIS folder. Python already includes SQLite, so there is nothing else to install or start.

1. **Back up first.** Copy your whole AIMIS folder.
2. Copy every file from this package into your AIMIS folder, replacing the old ones. Delete the old
   `templates/career.html` if it is still there.
3. In the AIMIS folder (venv on): `pip install -r requirements.txt`
4. Choose one:
   - **Keep your current data** (accounts, interviews, scores): start MySQL in XAMPP one last time, then run
     `python migrate_from_mysql.py`. It copies everything into `aimis.db`. After that you can close XAMPP for good.
   - **Start fresh** (groupmates): do nothing. `aimis.db` is created by itself the first time AIMIS starts, with the
     250 approved questions and the admin account `admin12345@gmail.com`.
5. `python check_setup.py` (all database lines should be [OK]), then `python app.py`.

Useful commands: `python db.py info` (rows per table), `python db.py make-admin you@email.com`,
`python db.py reset` (backs up and starts an empty database). To look inside the database, use
DB Browser for SQLite instead of SQLyog.

**Never push `aimis.db` to GitHub** (it has students' personal data; it is in `.gitignore`). Each groupmate has
their own `aimis.db`, so nobody sees anyone else's records, which also fixes the "same interview report on my
groupmate's PC" problem.

**Existing students:** the next time they log in, AIMIS asks for their profile and consent.
**Old reports:** they still open and show the old scores. Each one has a "Re-score with the new rubric" button,
which uses 1 Gemini request and does not record the answers again.

## Adviser's layout comments

| Comment | What changed |
|---|---|
| Modal / pop-up form | The career goal is now a pop-up form on the dashboard (no separate page). It opens by itself until the student picks a job, and from **Target job** in the sidebar or **Change** on the dashboard and start page. |
| Onboarding first, not the goal right away | The onboarding is now a short "get to know you" form in 3 steps: **About you** (age, course, what you are now, year level), **Your goal** (the job you want to pursue), **Your experience** (work experience, real interviews before, confidence on a 4-point scale with no neutral, and up to 3 things to improve). The live interviewer uses this background only to fit its questions to the student (e.g. a 4th-year IT student with OJT who has never had a real interview); it is never sent to the scoring step. Students can change it later on **My profile**. "How AIMIS works" is a separate page in the sidebar. |
| Login → onboarding → consent → dashboard | Students follow this order on their first login (existing students too, once). The data privacy consent (RA 10173) is its own page, given once for all interviews (it also covers the profile), instead of a checkbox on every start page. It can be reviewed or withdrawn under **Privacy & consent**. |
| Light mode by default | AIMIS always opens in light mode. The login, register and password pages are light only (no switch). After logging in, the student can switch to dark mode in the sidebar, and the choice is remembered. |
| Colors: no purple, light blue for trust | All purple and indigo colors were replaced with light blue and blue (welcome banner, accents, button text). |
| Redundant logo on login | The big logo inside the login and register cards was removed; the logo stays only at the top left. |
| Dashboard too compact / looks like an admin dashboard | The student home page is roomier and friendlier: a welcome banner with one big Start button and the target job, "Your progress" in plain words, "Work on next", bigger skill cards, the skill rings, and recent interviews. |
| Onboarding: less scrolling, no switch or logout | The onboarding steps and the consent page use the full width (e.g. job cards in 4 columns, two experience questions side by side, consent text on the right and the agree box on the left), so each step fits on one screen at 1366×768 and up. These pages show only the logo, always in light mode; the dark mode switch and Log out are only in the dashboard sidebar. |
| Sidebar only on the home page | The sidebar now shows only on the student's home page (and on the admin panel, which is the admin's dashboard). Every other page (report, history, start interview, profile...) has a top bar with the logo, a **Home** link and the profile menu at the top right (Home, Interview history, My profile, Target job, Privacy & consent, My data). The dark mode switch and Log out stay in the home page sidebar. |
| No gradient colors; less scrolling on the home page | The welcome banner is solid light blue (no gradient). The home page is one screen at 1920×1080: welcome banner with the Start button, target job and quick skill shortcuts, Your progress, Your interview skills, Work on next, and a short Recent interviews list (the full list is on Interview history). |
| Profile at the top right | The student's avatar, name and target job are at the top right of every page. It opens a menu: My profile, Target job, Privacy & consent, My data. |
| Dead space in interview history | History is now cards in a grid (score, Answer and Delivery bars, one button), with its own **Interview history** page and filters (All / Completed / Unfinished). |
| Sidebar, logout at the very bottom | The home page has a left sidebar with the pages (Home, Start interview, Interview history, How AIMIS works; admins see the admin sections). Account items (My profile, Target job, Privacy & consent, My data) are only in the profile menu at the top right, so nothing is listed twice. Dark mode and **Log out** are at the bottom. On phones it opens with the menu button. The interview room itself has no sidebar, so students don't leave by accident. |

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
   - decides what comes next. If the answer has **substance** (a real situation, something the student did, a
     decision with reasons, a result or a lesson), it asks a **follow-up** that digs deeper into one specific thing
     they said. If the answer has **no substance** (empty, off-topic, "I don't know", only general claims), it does
     not follow up and **moves on to the next main question**, written from the conversation so far, the target
     job, the skill and the level, without repeating an earlier question.
   The AI also states its decision (`substance: true/false`), and AIMIS enforces it: no follow-up is ever asked on an
   answer without substance. When it moves on, the reply adds a short bridge ("Thanks, Ana, that gives me a good
   picture of your OJT. Let's talk about working under pressure."), and the next question builds on what the
   student already said when possible ("Since you handled walk-in clients during your OJT, tell me about a time a
   client was upset with you."). The terminal shows each decision, e.g.
   `[AIMIS Bot] the answer has substance: follow-up question written live` or
   `[AIMIS Bot] the answer has no substance to dig into: moving on, next question written live from the conversation`.
3. The robot asks it out loud, and the conversation continues until the chosen number of main questions
   (including the introduction) is reached. Follow-ups don't count toward that number. Each main question can get
   up to 2 follow-ups (`MAX_FOLLOW_UPS` in `.env`) and the introduction up to 1, so the interview keeps a
   predictable length.

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
