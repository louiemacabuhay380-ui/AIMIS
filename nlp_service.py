import re
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize, sent_tokenize

_stemmer = PorterStemmer()
_STOPWORDS = set(stopwords.words("english"))
FILLERS = {"um", "uh", "uhm", "er", "erm", "ah", "hmm"}

# Words that signal a structured answer (STAR: situation, task, action, result)
STAR_KEYWORDS = ["situation", "task", "goal", "challenge", "action", "decide", "plan",
                 "result", "outcome", "learn", "improve", "achieve", "success"]

# Soft-skill keywords per question category. Your group can edit these lists.
CATEGORY_KEYWORDS = {
    "Communication": ["listen", "explain", "clarify", "understand", "feedback", "message", "present", "discuss"],
    "Teamwork": ["team", "together", "collaborate", "support", "role", "share", "cooperate", "group"],
    "Problem Solving": ["problem", "solution", "analyze", "identify", "cause", "option", "solve", "test"],
    "Adaptability": ["change", "adjust", "adapt", "flexible", "new", "learn", "quickly", "open"],
    "Time Management": ["deadline", "prioritize", "schedule", "plan", "organize", "time", "task", "manage"],
    "Leadership": ["lead", "guide", "motivate", "initiative", "responsibility", "decision", "delegate", "inspire"],
    "Work Ethic & Attitude": ["responsible", "professional", "honest", "mistake", "improve", "commit", "effort", "criticism"],
    "Emotional Intelligence": ["calm", "stress", "empathy", "feel", "emotion", "understand", "patient", "aware"],
    "Behavioral": ["situation", "team", "problem", "deadline", "mistake", "handle", "result", "learn"],
    "General": ["strength", "goal", "experience", "skill", "passion", "growth", "career", "value"],
}


def analyze_text(transcript, category):
    """Measure an answer's length, vocabulary, and keyword use with NLTK."""
    text = transcript or ""
    sentences = sent_tokenize(text)
    words = [w.lower() for w in word_tokenize(text) if re.fullmatch(r"[a-zA-Z][a-zA-Z']*", w)]
    spoken = [w for w in words if w not in FILLERS]
    content = [w for w in spoken if w not in _STOPWORDS]   # meaningful words only

    diversity = round(len(set(content)) / len(content) * 100, 2) if content else 0.0

    # Stemming lets "leading", "led", and "leader" match the keyword "lead"
    stems = {_stemmer.stem(w) for w in content}
    keywords = set(CATEGORY_KEYWORDS.get(category, []) + STAR_KEYWORDS)
    found = sorted(k for k in keywords if _stemmer.stem(k) in stems)

    return {
        "word_count": len(spoken),
        "sentence_count": len(sentences),
        "vocabulary_diversity": diversity,
        "keyword_count": len(found),
        "keywords_found": ", ".join(found)[:500],
    }