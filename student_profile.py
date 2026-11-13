"""Student profile asked during onboarding ("know your student"): age, studies, what they want to pursue,
work and interview experience, and what they want to improve.

The interviewer uses it as background (e.g. "a 4th-year IT student with OJT experience who has never had a real
job interview"), so its questions fit the student. It is never used for scoring.
"""
import re

import account_actions
import careers

AGE_MIN, AGE_MAX = 15, 70

# At most 4 choices per question (adviser); anything else is typed in under "Others"
OTHERS = "Others"
STATUS = ["Senior high school student", "College student", "Fresh graduate"]
YEAR_LEVELS = ["1st year", "2nd year", "3rd year", "4th year"]
WORK = [("none", "None yet"), ("ojt", "OJT or internship"), ("part_time", "Part-time job"),
        ("full_time", "Full-time job")]
INTERVIEWS = [("never", "Never"), ("few", "1 to 2 times"), ("many", "3 times or more")]
# 4 levels, no neutral middle (same as the paper's Likert scale)
CONFIDENCE = [(1, "Not confident"), (2, "Slightly confident"), (3, "Fairly confident"), (4, "Very confident")]
FOCUS = ["Speaking confidently", "Eye contact and body language", "Clear, specific answers"]
CAREERS_SHOWN = 3            # the first 3 career goals as cards; any other job is typed in under "Others"
OTHER_MAX = 60
YEAR_OTHER_MAX = 20   # fits the year_level column (VARCHAR 20)
MAX_FOCUS = 3
COURSE_MAX = 100

COLUMNS = ["age", "education_status", "course", "year_level", "work_experience", "interview_experience",
           "interview_confidence", "focus_areas"]


def _typed(value, minimum=2):
    """Text typed under "Others": letters, numbers and simple punctuation, at most 60 characters."""
    value = " ".join(str(value or "").split())[:OTHER_MAX]
    value = re.sub(r"[^A-Za-zÀ-ÿñÑ0-9 &/,.()'+-]", "", value).strip(" .,-")
    return value if len(value) >= minimum else ""


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
    if status == OTHERS:
        status = _typed(form.get("education_status_other"))[:40] or None
        if not status:
            problems.append('Type what you are now under "Others" (e.g. Working professional).')
    elif status not in STATUS:
        status = None
        problems.append("Choose what you are now.")
    course = " ".join(str(form.get("course", "")).split())[:COURSE_MAX] or None
    year = form.get("year_level", "")
    if status != "College student":
        year = None
    elif year == OTHERS:
        year = _typed(form.get("year_level_other"))[:YEAR_OTHER_MAX] or None
        if not year:
            problems.append('Type your year level under "Others" (e.g. 5th year).')
    elif year not in YEAR_LEVELS:
        year = None
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
    picked = form.getlist("focus_areas") if hasattr(form, "getlist") else []
    focus = [f for f in picked if f in FOCUS]
    if OTHERS in picked:
        typed = _typed(form.get("focus_other"))
        if typed:
            focus.append(typed)
    focus = focus[:MAX_FOCUS]
    career = careers.from_form(form)
    if career and career not in careers.NAMES:
        career = account_actions.match_career(career)      # "teacher" -> "Teaching and education"
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
            "age_max": AGE_MAX, "course_max": COURSE_MAX, "others": OTHERS, "careers_shown": CAREERS_SHOWN,
            "other_max": OTHER_MAX, "year_other_max": YEAR_OTHER_MAX}
