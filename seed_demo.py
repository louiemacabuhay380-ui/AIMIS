"""Creates a ready-to-show demo account for the defense: 4 completed interviews over 4 weeks,
with answers that improve over time, scored by the real AI (Gemini, or Ollama when Gemini fails).

    python seed_demo.py

Log in with:  demo@aimis.local  /  demo1234   (change DEMO_PASSWORD below if you like)
Running it again deletes the old demo interviews and makes fresh ones. Real students are never touched.
No voice recordings are created; the answers are typed transcripts."""
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

import app as aimis
import my_data

DEMO_EMAIL = "demo@aimis.local"
DEMO_NAME = "Demo Student"
DEMO_PASSWORD = "demo1234"

# (category, days ago, [(question, answer, speech, camera)])
# speech = (words per minute, filler words, long pauses, fluency, confidence, clarity)
# camera = (eye contact, face visible, facial expression, gestures, expressive gestures %, face touching %)
INTERVIEWS = [
    ("Teamwork", 24, [
        ("Tell me about a time you worked in a group to finish a school project.",
         "Um, in our thesis group, uh, we had to make a system. I did the, ano, the design part. "
         "We finished it naman. It was okay, we just worked together.",
         (118, 5, 3, 55, 50, 68), (52, 92, 48, 55, 10, 22)),
        ("How do you handle a groupmate who does not do their part?",
         "I just, um, talk to them. Then we continue the work. Parang ganun lang.",
         (110, 4, 2, 52, 48, 66), (48, 90, 45, 50, 8, 25)),
        ("Describe a disagreement in your group and how it was resolved.",
         "We argued about the color of the poster. Uh, the leader decided. So it was fine.",
         (115, 3, 2, 58, 52, 70), (55, 93, 50, 52, 12, 18)),
    ]),
    ("Problem Solving", 17, [
        ("Tell me about a difficult problem you solved in school.",
         "Our code for the capstone kept crashing when we saved the data. Um, I searched the error online "
         "and found out the database connection was closing early. I fixed it and it worked.",
         (126, 3, 2, 64, 60, 74), (60, 95, 55, 60, 18, 15)),
        ("How do you decide between two possible solutions?",
         "I usually pick the faster one because we always have deadlines. Uh, sometimes I ask my groupmates.",
         (122, 2, 2, 62, 58, 72), (58, 94, 54, 58, 15, 14)),
        ("Describe a time your first plan did not work.",
         "My study plan for finals did not work because I had too many subjects. So I made a new schedule "
         "with one subject per day, and um, my grades were better.",
         (128, 2, 1, 66, 62, 75), (62, 95, 58, 62, 20, 12)),
    ]),
    ("Adaptability", 10, [
        ("How do you adjust when you join a new group or team?",
         "When I joined our org last semester, I listened first during the meetings to see how they work. "
         "Then I volunteered to make the event poster, and after that they invited me to the planning committee.",
         (132, 1, 1, 74, 70, 80), (70, 96, 64, 70, 28, 8)),
        ("Tell me about a time you had to learn something new quickly.",
         "For our thesis prototype, I had to learn Figma in two days. I watched tutorials at night and copied "
         "sample designs to practice. I finished the screens on time and our adviser approved them with small changes.",
         (135, 1, 0, 78, 74, 82), (72, 97, 66, 72, 30, 6)),
        ("How do you handle sudden changes to your plans?",
         "Um, I just go with the flow. Whatever happens, I adjust.",
         (120, 2, 1, 65, 60, 76), (66, 95, 60, 65, 22, 10)),
    ]),
    ("Communication", 3, [
        ("How do you explain a complicated idea to someone who is not familiar with it?",
         "I start with a simple example they already know. When I explained our mock interview system to my "
         "parents, I compared it to practicing with a friend who gives you a score. Then I showed them the "
         "report on my phone, and they understood how it works.",
         (138, 0, 0, 84, 80, 86), (78, 98, 72, 76, 35, 4)),
        ("Tell me about a time you had to give feedback to a groupmate.",
         "A groupmate's slides had too much text. Instead of saying it was bad, I told him which slide was "
         "the clearest and suggested we make the others like it. He changed them, and our presentation got "
         "one of the highest grades in class.",
         (136, 1, 0, 82, 78, 85), (76, 98, 70, 74, 32, 5)),
        ("How do you make sure people understand your instructions?",
         "I give the steps one at a time and ask them to repeat the main point. During our org event I also "
         "posted a short checklist in our group chat, so the volunteers had the same instructions. Nobody missed "
         "their task that day.",
         (134, 0, 1, 83, 79, 86), (77, 97, 71, 75, 33, 5)),
    ]),
]


def main():
    conn = aimis.get_db()
    cursor = conn.cursor(dictionary=True)

    # 1. The demo account (created once, password reset every run)
    cursor.execute("SELECT user_id FROM users WHERE email = %s", (DEMO_EMAIL,))
    row = cursor.fetchone()
    if row:
        user_id = row["user_id"]
        cursor.execute("UPDATE users SET password = %s, full_name = %s WHERE user_id = %s",
                       (generate_password_hash(DEMO_PASSWORD), DEMO_NAME, user_id))
        conn.commit()
        my_data.delete_user_data(conn, aimis.app.root_path, user_id)   # old demo interviews
        print("Removed the old demo interviews.")
    else:
        cursor.execute("INSERT INTO users (full_name, email, password) VALUES (%s, %s, %s)",
                       (DEMO_NAME, DEMO_EMAIL, generate_password_hash(DEMO_PASSWORD)))
        user_id = cursor.lastrowid
        conn.commit()
        print("Created the demo account.")

    # 2. Demo questions are kept out of real interviews and out of the admin's question lists
    cursor.execute("DELETE FROM question_bank WHERE source = 'demo' AND question_id NOT IN "
                   "(SELECT question_id FROM interview_questions)")
    conn.commit()

    created = []
    for category, days_ago, items in INTERVIEWS:
        finished = datetime.now().replace(microsecond=0) - timedelta(days=days_ago)
        cursor.execute("""INSERT INTO interviews (user_id, category, difficulty, number_of_questions,
                                                  status, started_at, completed_at)
                          VALUES (%s, %s, 'Beginner', %s, 'completed', %s, %s)""",
                       (user_id, category, len(items), finished - timedelta(minutes=12), finished))
        interview_id = cursor.lastrowid
        cursor.execute("""INSERT INTO consents (user_id, interview_id, consent_given, consent_version)
                          VALUES (%s, %s, 1, %s)""", (user_id, interview_id, aimis.CONSENT_VERSION))
        for order, (question, answer, speech, camera) in enumerate(items, start=1):
            cursor.execute("""INSERT INTO question_bank (category, difficulty, question_text, is_active,
                                                         source, review_status)
                              VALUES (%s, 'Beginner', %s, 0, 'demo', 'demo')""", (category, question))
            question_id = cursor.lastrowid
            cursor.execute("""INSERT INTO interview_questions (interview_id, question_id, question_order)
                              VALUES (%s, %s, %s)""", (interview_id, question_id, order))
            iq_id = cursor.lastrowid
            seconds = round(len(answer.split()) / speech[0] * 60, 1)
            cursor.execute("""INSERT INTO responses (interview_question_id, transcript, audio_path, duration)
                              VALUES (%s, %s, NULL, %s)""", (iq_id, answer, seconds))
            response_id = cursor.lastrowid
            wpm, fillers, pauses, fluency, confidence, clarity = speech
            cursor.execute("""INSERT INTO speech_analysis (response_id, speaking_rate, filler_word_count, pause_count,
                                                           speech_duration, fluency_score, confidence_score, clarity_score)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                           (response_id, wpm, fillers, pauses, seconds, fluency, confidence, clarity))
            eye, visible, face, gesture, expressive, touch = camera
            cursor.execute("""INSERT INTO behavior_analysis (response_id, eye_contact_score, face_visibility_score,
                                                             facial_expression_score, gesture_score, smile_ratio,
                                                             gesture_ratio, frames_analyzed, hands_visible_ratio,
                                                             expressive_gesture_ratio, face_touch_ratio)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                           (response_id, eye, visible, face, gesture, face / 3, gesture / 4, 600,
                            min(100, gesture + 10), expressive, touch))
        conn.commit()
        created.append((interview_id, category))
    conn.close()

    # 3. Score them with the real AI, oldest first (so later feedback can compare with earlier ones)
    for n, (interview_id, category) in enumerate(created, start=1):
        print(f"Scoring demo interview {n}/{len(created)} ({category})... this calls the AI")
        aimis.evaluate_interview(interview_id)

    print(f"\nDone. Log in with  {DEMO_EMAIL}  /  {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
