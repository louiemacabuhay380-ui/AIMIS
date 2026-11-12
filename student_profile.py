"""Student profile asked during onboarding ("know your student"): age, studies, what they want to pursue,
work and interview experience, and what they want to improve.

The interviewer uses it as background (e.g. "a 4th-year IT student with OJT experience who has never had a real
job interview"), so its questions fit the student. It is never used for scoring.
"""
import careers

AGE_MIN, AGE_MAX = 15, 70

STATUS = ["Senior high school student", "College student", "Fresh graduate", "Working professional",
          "Career shifter / returning to work"]
YEAR_LEVELS = ["1st year", "2nd year", "3rd year", "4th year", "5th year"]
WORK = [("none", "None yet"), ("ojt", "OJT or internship"), ("part_time", "Part-time job"),
        ("full_time", "Full-time job")]
INTERVIEWS = [("never", "Never"), ("few", "1 to 2 times"), ("many", "3 times or more")]
# 4 levels, no neutral middle (same as the paper's Likert scale)
CONFIDENCE = [(1, "Not confident"), (2, "Slightly confident"), (3, "Fairly confident"), (4, "Very confident")]
FOCUS = ["Answering clearly and directly", "Giving specific examples (STAR)", "Speaking confidently",
         "Fewer \"um\" and \"uh\"", "Eye contact", "Body language and gestures", "Handling difficult questions",
         "Introducing myself"]
MAX_FOCUS = 3
COURSE_MAX = 100

COLUMNS = ["age", "education_status", "course", "year_level", "work_experience", "interview_experience",
           "interview_confidence", "focus_areas"]


def _label(options, key):
    return dict(options).get(key, "")


def from_form(form):
    """(profile dict, career goal, list of problems) from the onboarding or profile form."""
    problems = []
    try:
        age = int(form.get("age", ""))
        if not AGE_MIN <= age <= AGE_MAX:
            raise ValueError
    except ValueError:
        age = None
        problems.append(f"Enter your age ({AGE_MIN} to {AGE_MAX}).")
    status = form.get("education_status", "")
    if status not in STATUS:
        status = None
        problems.append("Choose what you are now (student, graduate, working...).")
    course = " ".join(str(form.get("course", "")).split())[:COURSE_MAX] or None
    year = form.get("year_level", "")
    year = year if status == "College student" and year in YEAR_LEVELS else None
    work = form.get("work_experience", "")
    if work not in dict(WORK):
        work = None
        problems.append("Choose your work experience.")
    interviews = form.get("interview_experience", "")
    if interviews not in dict(INTERVIEWS):
        interviews = None
        problems.append("Choose how many real job interviews you've had.")
    try:
        confidence = int(form.get("interview_confidence", ""))
        if confidence not in dict(CONFIDENCE):
            raise ValueError
    except ValueError:
        confidence = None
        problems.append("Choose how confident you feel in job interviews.")
    focus = [f for f in form.getlist("focus_areas") if f in FOCUS][:MAX_FOCUS] if hasattr(form, "getlist") else []
    career = careers.from_form(form)
    if not career:
        problems.append("Choose the job you want to pursue (or type it in, at least 3 letters).")
    profile = {"age": age, "education_status": status, "course": course, "year_level": year,
               "work_experience": work, "interview_experience": interviews, "interview_confidence": confidence,
               "focus_areas": "|".join(focus) or None}
    return profile, career, problems


def focus_list(row):
    return [f for f in ((row or {}).get("focus_areas") or "").split("|") if f]


def describe(row):
    """One line about the student for the AI interviewer, or "" if there is no profile."""
    if not row or not row.get("education_status"):
        return ""
    parts = []
    if row.get("age"):
        parts.append(f"{row['age']} years old")
    studies = row["education_status"]
    if row.get("course"):
        studies += f", {row['course']}"
    if row.get("year_level"):
        studies += f", {row['year_level']}"
    parts.append(studies)
    if row.get("work_experience"):
        parts.append("work experience: " + _label(WORK, row["work_experience"]).lower())
    if row.get("interview_experience"):
        parts.append("real job interviews before: " + _label(INTERVIEWS, row["interview_experience"]).lower())
    if row.get("interview_confidence"):
        parts.append("feels " + _label(CONFIDENCE, row["interview_confidence"]).lower() + " in interviews")
    focus = focus_list(row)
    if focus:
        parts.append("wants to improve: " + ", ".join(focus).lower())
    return ("Candidate background (from their AIMIS profile; use it only to make questions fit them, "
            "never to judge them): " + "; ".join(parts) + ".")


def load(cursor, user_id):
    cursor.execute(f"SELECT career_goal, {', '.join(COLUMNS)} FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    if row is not None and not isinstance(row, dict):
        row = dict(zip(["career_goal"] + COLUMNS, row))
    return row or {}


def save(cursor, user_id, profile, career):
    sets = ", ".join(f"{c} = %s" for c in COLUMNS)
    cursor.execute(f"UPDATE users SET {sets}, career_goal = %s WHERE user_id = %s",
                   [profile[c] for c in COLUMNS] + [career, user_id])


def options():
    return {"status": STATUS, "years": YEAR_LEVELS, "work": WORK, "interviews": INTERVIEWS,
            "confidence": CONFIDENCE, "focus": FOCUS, "max_focus": MAX_FOCUS, "age_min": AGE_MIN,
            "age_max": AGE_MAX, "course_max": COURSE_MAX}
