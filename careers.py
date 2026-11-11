"""Career goals (panel comment 6): each student picks the job they are preparing for after creating an account.
The interview questions are then set in that job's context. The skills scored are still communication and
behavior; the career goal only changes WHAT situations the questions are about.

Edit this list to match the programs of your college. "context" tells the AI what kind of work the job involves.
"""
import re

CAREER_GOALS = [
    ("IT professional", "software or web development, IT support, networking, or systems administration"),
    ("Customer service / BPO", "call center, customer care, or technical support accounts"),
    ("Business and office administration", "office administration, human resources, or operations"),
    ("Accounting and finance", "bookkeeping, accounting, banking, or audit"),
    ("Sales and marketing", "sales, retail, digital marketing, or social media"),
    ("Teaching and education", "classroom teaching, tutoring, or training"),
    ("Hospitality and tourism", "hotels, restaurants, travel, or events"),
    ("Healthcare", "nursing, caregiving, or clinic and hospital work"),
    ("Criminology and public safety", "law enforcement, security, or corrections"),
    ("Engineering and technical work", "engineering, technicians, or manufacturing"),
]
NAMES = [name for name, _ in CAREER_GOALS]
OTHER = "Other"
MAX_LENGTH = 60


def context(goal):
    """Short description of the job for the AI (the goal itself if the student typed their own)."""
    for name, ctx in CAREER_GOALS:
        if name == goal:
            return f"{name} ({ctx})"
    return goal or "an entry-level job"


def clean_custom(text):
    """A typed career goal: letters, numbers and simple punctuation only, at most 60 characters."""
    text = " ".join(str(text or "").split())[:MAX_LENGTH]
    text = re.sub(r"[^A-Za-z0-9 &/,.()'+-]", "", text).strip(" .,-")
    return text if len(text) >= 3 else ""


def from_form(form):
    """The career goal chosen on the form, or "" if it is missing or invalid."""
    picked = (form.get("career_goal") or "").strip()
    if picked in NAMES:
        return picked
    if picked == OTHER:
        return clean_custom(form.get("career_other"))
    return ""
