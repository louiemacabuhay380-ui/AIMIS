"""Account requests typed into AIMIS Coach ("change my name to Juan Cruz", "palitan career ko ng teacher").

Recognized with fixed rules, never by the AI, so the AI can't change anything by itself:
  - name and career goal: the chatbot proposes the change and saves it only after the student presses Confirm;
  - password, email and deleting data: the chatbot explains and links to the right page.
"""
import re
import secrets
import time

import careers

CHANGE = r"(?:change|update|edit|set|correct|fix|replace|switch|palitan|palitan\s+mo|baguhin|gawing|gawin)"
TO = r"(?:to|into|as|with|ng|sa|ay|:|=|->)"
NAME_WORD = r"(?:full\s+)?(?:name|pangalan|username)"
CAREER_WORD = r"(?:career\s+goal|career|target\s+job|target\s+career|job\s+goal|dream\s+job|trabaho)"
MY = r"(?:my\s+|ang\s+|yung\s+|'?yung\s+)?"
KO = r"(?:\s+ko)?"
TAIL = r"(?:\s*(?:please|pls|po|thanks|thank\s+you|na\s+lang|naman)\b.*)?[\s.!?]*$"

NAME_SET = [
    re.compile(rf"\b{CHANGE}\s+{MY}{NAME_WORD}{KO}\s+{TO}\s*(?P<v>.+?){TAIL}", re.I),
    re.compile(rf"\brename\s+me\s+(?:to|as)\s+(?P<v>.+?){TAIL}", re.I),
    re.compile(rf"\bmy\s+(?:real\s+|correct\s+|new\s+)?name\s+(?:should\s+be|must\s+be)\s+(?P<v>.+?){TAIL}", re.I),
    re.compile(rf"\bmy\s+(?:real\s+|correct\s+)?name\s+is\s+(?P<v>.+?)\s*,?\s+(?:not|please\s+change|change\s+it)\b", re.I),
]
CAREER_SET = [
    re.compile(rf"\b{CHANGE}\s+{MY}{CAREER_WORD}{KO}\s+{TO}\s*(?P<v>.+?){TAIL}", re.I),
    re.compile(rf"\bmy\s+(?:new\s+)?(?:career\s+goal|target\s+job|career)\s+(?:is\s+now|should\s+be|is)\s+(?P<v>.+?){TAIL}", re.I),
    re.compile(rf"\bi\s+(?:now\s+)?want\s+to\s+(?:be|become|apply\s+as|work\s+as)\s+(?:an?\s+)?(?P<v>.+?)\s+(?:instead|now)\b", re.I),
]
NAME_ASK = re.compile(rf"\b{CHANGE}\b.*\b{NAME_WORD}\b|\b{NAME_WORD}\b.*\b(?:wrong|mali|typo|misspelled)\b", re.I)
CAREER_ASK = re.compile(rf"\b{CHANGE}\b.*\b{CAREER_WORD}\b", re.I)
PASSWORD = re.compile(r"\b(?:password|passcode)\b", re.I)
EMAIL = re.compile(rf"\b{CHANGE}\b.*\b(?:e-?mail)\b|\b(?:e-?mail)\b.*\b(?:wrong|mali)\b", re.I)
DELETE = re.compile(r"\b(?:delete|remove|erase|burahin|tanggalin)\b.*\b(?:account|data|interviews?|recordings?|history|records?)\b", re.I)

# Common words for each career goal, so "teacher" or "call center" finds the right one
CAREER_WORDS = {
    "IT professional": ["it", "programmer", "developer", "software", "web", "programming", "network", "networking",
                        "it support", "tech support", "computer", "system admin", "it professional"],
    "Customer service / BPO": ["bpo", "call center", "callcenter", "customer service", "csr", "agent"],
    "Business and office administration": ["admin", "office", "hr", "human resource", "business", "secretary"],
    "Accounting and finance": ["accountant", "accounting", "finance", "bank", "bookkeeper", "audit"],
    "Sales and marketing": ["sales", "marketing", "seller", "social media", "retail"],
    "Teaching and education": ["teacher", "teaching", "education", "tutor", "instructor", "guro"],
    "Hospitality and tourism": ["hotel", "tourism", "hospitality", "restaurant", "chef", "cook", "flight attendant"],
    "Healthcare": ["nurse", "nursing", "healthcare", "caregiver", "medical", "health"],
    "Criminology and public safety": ["police", "criminology", "security", "guard", "law enforcement"],
    "Engineering and technical work": ["engineer", "engineering", "technician", "mechanic", "electrician"],
}

NAME_OK = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿñÑ][A-Za-zÀ-ÖØ-öø-ÿñÑ .'\-]{1,99}$")
PENDING_SECONDS = 300


def _clean(value):
    value = (value or "").strip().strip('"\'“”‘’')
    value = re.sub(r"[\s.!?,]+$", "", value)
    return " ".join(value.split())


def clean_name(value):
    value = _clean(value)
    if not NAME_OK.match(value) or sum(c.isalpha() for c in value) < 2:
        return ""
    if value.islower() or value.isupper():          # "juan dela cruz" -> "Juan Dela Cruz"
        value = " ".join(w[:1].upper() + w[1:].lower() for w in value.split())
    return value


def match_career(value):
    value = _clean(value)
    low = value.lower()
    low = re.sub(r"^(?:an?|the)\s+", "", low)
    for name, _ in careers.CAREER_GOALS:
        if low == name.lower():
            return name
    best = None
    for name, words in CAREER_WORDS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", low):
                if best is None or len(w) > best[1]:
                    best = (name, len(w))
    if best:
        return best[0]
    return careers.clean_custom(value)


def detect(question):
    """What account request this message is, or None if it isn't one."""
    q = " ".join((question or "").split())
    if not q:
        return None
    for rx in NAME_SET:
        m = rx.search(q)
        if m:
            name = clean_name(m.group("v"))
            return {"kind": "name", "value": name} if name else {"kind": "name_invalid"}
    for rx in CAREER_SET:
        m = rx.search(q)
        if m:
            career = match_career(m.group("v"))
            return {"kind": "career", "value": career} if career else {"kind": "career_ask"}
    if DELETE.search(q):
        return {"kind": "delete"}
    if PASSWORD.search(q):
        return {"kind": "password"}
    if EMAIL.search(q):
        return {"kind": "email"}
    if NAME_ASK.search(q):
        return {"kind": "name_ask"}
    if CAREER_ASK.search(q):
        return {"kind": "career_ask"}
    return None


def reply_for(action, user, urls):
    """What the chatbot answers. Returns dict(text, confirm=bool, link=(label, url) or None)."""
    kind = action["kind"]
    if kind == "name":
        if action["value"] == user["full_name"]:
            return {"text": f"Your name is already **{user['full_name']}**, so there's nothing to change."}
        return {"text": f"Do you want to change your name from **{user['full_name']}** to **{action['value']}**? "
                        "This is the name shown on your dashboard and reports.", "confirm": True}
    if kind == "career":
        current = user.get("career_goal") or "not set"
        if action["value"] == user.get("career_goal"):
            return {"text": f"Your career goal is already **{current}**."}
        return {"text": f"Do you want to change your career goal from **{current}** to **{action['value']}**? "
                        "Your next interviews will be set in this job. Your past reports keep the job they were for.",
                "confirm": True}
    if kind == "name_invalid":
        return {"text": "I couldn't read that name. Use letters only, for example: **change my name to Juan Dela Cruz**."}
    if kind == "name_ask":
        return {"text": f"Sure. Your name is **{user['full_name']}** now. Type your new name like this: "
                        "**change my name to Juan Dela Cruz**, and I'll ask you to confirm."}
    if kind == "career_ask":
        options = "\n".join(f"- {name}" for name, _ in careers.CAREER_GOALS)
        return {"text": f"Your career goal is **{user.get('career_goal') or 'not set'}**. Type, for example, "
                        f"**change my career goal to Teaching and education**. You can pick one of these or type your own:\n{options}",
                "link": ("Open career goal page", urls["career"])}
    if kind == "password":
        return {"text": "For your security, I can't change passwords in the chat. Use **Forgot password** instead: "
                        "AIMIS emails you a link to set a new one.",
                "link": ("Go to Forgot password", urls["forgot"])}
    if kind == "email":
        return {"text": "Your email is the address you log in with, so it can't be changed in the chat. "
                        "Ask the AIMIS administrator to update it."}
    if kind == "delete":
        return {"text": "You can delete your interviews, or your whole account, on the **My data** page. "
                        "I can't delete data from the chat, so nothing is removed by mistake.",
                "link": ("Open My data", urls["my_data"])}
    return {"text": "Sorry, I can't do that here."}


def remember(session, action):
    """Keep the proposed change in the student's session until they confirm it (expires after 5 minutes)."""
    token = secrets.token_urlsafe(12)
    session["chat_action"] = {"id": token, "kind": action["kind"], "value": action["value"],
                              "expires": time.time() + PENDING_SECONDS}
    return token


def take(session, token):
    """The pending change with this id (removed from the session), or None if it is missing or expired."""
    pending = session.pop("chat_action", None)
    if not pending or pending.get("id") != token or pending.get("expires", 0) < time.time():
        return None
    return pending
