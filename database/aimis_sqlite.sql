-- AIMIS database for SQLite (no XAMPP / MySQL needed).
-- You don't run this file yourself: db.py creates aimis.db from it the first time AIMIS starts
-- (or run: python db.py init). Same tables and columns as the old MySQL database.
-- Dates are stored as local time text ("2026-11-12 18:30:00") and read back as Python datetimes.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name VARCHAR(150) NOT NULL,
  email VARCHAR(150) NOT NULL UNIQUE,
  password VARCHAR(255) NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'student',
  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
  is_active TINYINT NOT NULL DEFAULT 1,
  career_goal VARCHAR(80) DEFAULT NULL,
  onboarded_at DATETIME DEFAULT NULL,
  consent_version VARCHAR(10) DEFAULT NULL,
  consent_at DATETIME DEFAULT NULL,
  age TINYINT DEFAULT NULL,
  education_status VARCHAR(40) DEFAULT NULL,
  course VARCHAR(100) DEFAULT NULL,
  year_level VARCHAR(20) DEFAULT NULL,
  work_experience VARCHAR(20) DEFAULT NULL,
  interview_experience VARCHAR(20) DEFAULT NULL,
  interview_confidence TINYINT DEFAULT NULL,
  focus_areas VARCHAR(255) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS question_bank (
  question_id INTEGER PRIMARY KEY AUTOINCREMENT,
  question_text TEXT NOT NULL,
  category VARCHAR(100) NOT NULL,
  difficulty VARCHAR(12) NOT NULL CHECK (difficulty IN ('Beginner', 'Intermediate', 'Advanced')),
  is_active TINYINT DEFAULT 1,
  created_by INTEGER DEFAULT NULL REFERENCES users (user_id) ON DELETE SET NULL ON UPDATE CASCADE,
  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
  source VARCHAR(10) NOT NULL DEFAULT 'manual',
  review_status VARCHAR(10) NOT NULL DEFAULT 'approved',
  career_track VARCHAR(80) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS interviews (
  interview_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  category VARCHAR(100) NOT NULL,
  difficulty VARCHAR(12) NOT NULL CHECK (difficulty IN ('Beginner', 'Intermediate', 'Advanced')),
  number_of_questions INTEGER NOT NULL,
  overall_score DECIMAL(5,2) DEFAULT NULL,
  started_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
  completed_at DATETIME DEFAULT NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed', 'cancelled')),
  career_goal VARCHAR(80) DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS fk_interview_user ON interviews (user_id);

CREATE TABLE IF NOT EXISTS interview_questions (
  interview_question_id INTEGER PRIMARY KEY AUTOINCREMENT,
  interview_id INTEGER NOT NULL REFERENCES interviews (interview_id) ON DELETE CASCADE ON UPDATE CASCADE,
  question_id INTEGER NOT NULL REFERENCES question_bank (question_id) ON UPDATE CASCADE,
  question_order INTEGER NOT NULL,
  parent_iq_id INTEGER DEFAULT NULL,
  UNIQUE (interview_id, question_order)
);
CREATE INDEX IF NOT EXISTS fk_iq_question ON interview_questions (question_id);

CREATE TABLE IF NOT EXISTS responses (
  response_id INTEGER PRIMARY KEY AUTOINCREMENT,
  interview_question_id INTEGER NOT NULL REFERENCES interview_questions (interview_question_id) ON DELETE CASCADE ON UPDATE CASCADE,
  transcript TEXT DEFAULT NULL,
  audio_path VARCHAR(500) DEFAULT NULL,
  video_path VARCHAR(500) DEFAULT NULL,
  duration DECIMAL(8,2) DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS fk_response_interview_question ON responses (interview_question_id);

CREATE TABLE IF NOT EXISTS speech_analysis (
  speech_analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id INTEGER NOT NULL UNIQUE REFERENCES responses (response_id) ON DELETE CASCADE ON UPDATE CASCADE,
  speaking_rate DECIMAL(6,2) DEFAULT NULL,
  filler_word_count INTEGER DEFAULT 0,
  pause_count INTEGER DEFAULT 0,
  speech_duration DECIMAL(8,2) DEFAULT NULL,
  fluency_score DECIMAL(5,2) DEFAULT NULL,
  total_pause_time DECIMAL(6,2) DEFAULT NULL,
  longest_pause DECIMAL(6,2) DEFAULT NULL,
  average_pause DECIMAL(6,2) DEFAULT NULL,
  pitch_variation DECIMAL(5,2) DEFAULT NULL,
  average_volume DECIMAL(6,2) DEFAULT NULL,
  volume_variation DECIMAL(5,2) DEFAULT NULL,
  speech_ratio DECIMAL(5,2) DEFAULT NULL,
  confidence_score DECIMAL(5,2) DEFAULT NULL,
  clarity_score DECIMAL(5,2) DEFAULT NULL,
  transcribed_by VARCHAR(20) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS nlp_analysis (
  nlp_analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id INTEGER NOT NULL UNIQUE REFERENCES responses (response_id) ON DELETE CASCADE ON UPDATE CASCADE,
  relevance_score DECIMAL(5,2) DEFAULT NULL,
  clarity_score DECIMAL(5,2) DEFAULT NULL,
  completeness_score DECIMAL(5,2) DEFAULT NULL,
  grammar_score DECIMAL(5,2) DEFAULT NULL,
  word_count INTEGER DEFAULT NULL,
  sentence_count INTEGER DEFAULT NULL,
  vocabulary_diversity DECIMAL(5,2) DEFAULT NULL,
  keyword_count INTEGER DEFAULT NULL,
  keywords_found VARCHAR(500) DEFAULT NULL,
  directness_score DECIMAL(5,2) DEFAULT NULL,
  specificity_score DECIMAL(5,2) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS behavior_analysis (
  behavior_analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id INTEGER NOT NULL UNIQUE REFERENCES responses (response_id) ON DELETE CASCADE ON UPDATE CASCADE,
  eye_contact_score DECIMAL(5,2) DEFAULT NULL,
  face_visibility_score DECIMAL(5,2) DEFAULT NULL,
  facial_expression_score DECIMAL(5,2) DEFAULT NULL,
  gesture_score DECIMAL(5,2) DEFAULT NULL,
  smile_ratio DECIMAL(5,2) DEFAULT NULL,
  gesture_ratio DECIMAL(5,2) DEFAULT NULL,
  frames_analyzed INTEGER DEFAULT NULL,
  hands_visible_ratio DECIMAL(5,2) DEFAULT NULL,
  expressive_gesture_ratio DECIMAL(5,2) DEFAULT NULL,
  face_touch_ratio DECIMAL(5,2) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
  evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  interview_id INTEGER NOT NULL UNIQUE REFERENCES interviews (interview_id) ON DELETE CASCADE ON UPDATE CASCADE,
  response_quality_score DECIMAL(5,2) DEFAULT NULL,
  speech_performance_score DECIMAL(5,2) DEFAULT NULL,
  behavioral_score DECIMAL(5,2) DEFAULT NULL,
  overall_score DECIMAL(5,2) DEFAULT NULL,
  evaluated_at DATETIME DEFAULT (datetime('now', 'localtime')),
  scored_by VARCHAR(20) DEFAULT NULL,
  delivery_score DECIMAL(5,2) DEFAULT NULL,
  performance_profile VARCHAR(20) DEFAULT NULL,
  rubric_version VARCHAR(10) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
  interview_id INTEGER NOT NULL REFERENCES interviews (interview_id) ON DELETE CASCADE ON UPDATE CASCADE,
  strengths TEXT DEFAULT NULL,
  areas_to_improve TEXT DEFAULT NULL,
  recommendations TEXT DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS fk_feedback_interview ON feedback (interview_id);

CREATE TABLE IF NOT EXISTS feedback_items (
  item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  interview_id INTEGER NOT NULL,
  kind VARCHAR(12) NOT NULL,
  answer_no INTEGER DEFAULT NULL,
  point TEXT DEFAULT NULL,
  quote TEXT DEFAULT NULL,
  fix TEXT DEFAULT NULL,
  example TEXT DEFAULT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_item_interview ON feedback_items (interview_id);

CREATE TABLE IF NOT EXISTS answer_feedback (
  response_id INTEGER PRIMARY KEY,
  feedback TEXT DEFAULT NULL,
  weak_quote TEXT DEFAULT NULL,
  better_answer TEXT DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS skill_labels (
  label_id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id INTEGER NOT NULL,
  skill VARCHAR(40) NOT NULL,
  rating VARCHAR(10) NOT NULL,
  reason VARCHAR(300) DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_label_response ON skill_labels (response_id);
CREATE INDEX IF NOT EXISTS idx_label_skill ON skill_labels (skill);

CREATE TABLE IF NOT EXISTS consents (
  consent_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  interview_id INTEGER NOT NULL REFERENCES interviews (interview_id) ON DELETE CASCADE ON UPDATE CASCADE,
  consent_given TINYINT NOT NULL DEFAULT 0,
  consent_version VARCHAR(50) NOT NULL,
  consented_at DATETIME DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS fk_consent_user ON consents (user_id);
CREATE INDEX IF NOT EXISTS fk_consent_interview ON consents (interview_id);

CREATE TABLE IF NOT EXISTS rag_chunks (
  chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  interview_id INTEGER NOT NULL,
  response_id INTEGER DEFAULT NULL,
  question_order INTEGER DEFAULT NULL,
  kind VARCHAR(20) NOT NULL,
  content TEXT NOT NULL,
  embedding TEXT DEFAULT NULL,
  embed_model VARCHAR(80) DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_chunk_user ON rag_chunks (user_id);
CREATE INDEX IF NOT EXISTS idx_chunk_interview ON rag_chunks (interview_id);

CREATE TABLE IF NOT EXISTS chat_messages (
  message_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  interview_id INTEGER DEFAULT NULL,
  role VARCHAR(10) NOT NULL,
  content TEXT NOT NULL,
  sources TEXT DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_messages (user_id);

CREATE TABLE IF NOT EXISTS human_ratings (
  rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id INTEGER NOT NULL,
  rater_id INTEGER NOT NULL,
  relevance TINYINT NOT NULL,
  clarity TINYINT DEFAULT NULL,
  completeness TINYINT NOT NULL,
  grammar TINYINT NOT NULL,
  comment VARCHAR(500) DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
  directness TINYINT DEFAULT NULL,
  specificity TINYINT DEFAULT NULL,
  UNIQUE (response_id, rater_id)
);
CREATE INDEX IF NOT EXISTS idx_rating_rater ON human_ratings (rater_id);
