-- ================================================================
-- AIMIS database changes made during development.
-- Check first with DESCRIBE <table>; and run ONLY the blocks whose
-- columns are missing. Running a block twice gives "Duplicate column".
-- ================================================================

-- 1) NLTK text measurements
ALTER TABLE nlp_analysis
  ADD COLUMN word_count INT NULL,
  ADD COLUMN sentence_count INT NULL,
  ADD COLUMN vocabulary_diversity DECIMAL(5,2) NULL,
  ADD COLUMN keyword_count INT NULL,
  ADD COLUMN keywords_found VARCHAR(500) NULL;

-- 2) librosa speech measurements + confidence
ALTER TABLE speech_analysis
  ADD COLUMN total_pause_time DECIMAL(6,2) NULL,
  ADD COLUMN longest_pause DECIMAL(6,2) NULL,
  ADD COLUMN average_pause DECIMAL(6,2) NULL,
  ADD COLUMN pitch_variation DECIMAL(5,2) NULL,
  ADD COLUMN average_volume DECIMAL(6,2) NULL,
  ADD COLUMN volume_variation DECIMAL(5,2) NULL,
  ADD COLUMN speech_ratio DECIMAL(5,2) NULL,
  ADD COLUMN confidence_score DECIMAL(5,2) NULL;

-- 3) Gemini speech clarity rating
ALTER TABLE speech_analysis ADD COLUMN clarity_score DECIMAL(5,2) NULL;

-- 4) Behavioral analysis (eye contact, facial expression, gestures; posture removed)
ALTER TABLE behavior_analysis
  DROP COLUMN posture_score,
  MODIFY eye_contact_score DECIMAL(5,2) NULL,
  MODIFY face_visibility_score DECIMAL(5,2) NULL,
  ADD COLUMN facial_expression_score DECIMAL(5,2) NULL,
  ADD COLUMN gesture_score DECIMAL(5,2) NULL,
  ADD COLUMN smile_ratio DECIMAL(5,2) NULL,
  ADD COLUMN gesture_ratio DECIMAL(5,2) NULL,
  ADD COLUMN frames_analyzed INT NULL;

-- 5) Detailed hand gestures: hands visible, expressive gestures while speaking, face touching
ALTER TABLE behavior_analysis
  ADD COLUMN hands_visible_ratio DECIMAL(5,2) NULL,
  ADD COLUMN expressive_gesture_ratio DECIMAL(5,2) NULL,
  ADD COLUMN face_touch_ratio DECIMAL(5,2) NULL;

-- 6) Admin panel: deactivate accounts, and AI-written questions waiting for review
ALTER TABLE users ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1;
ALTER TABLE question_bank
  ADD COLUMN source VARCHAR(10) NOT NULL DEFAULT 'manual',
  ADD COLUMN review_status VARCHAR(10) NOT NULL DEFAULT 'approved';
-- Let the role column hold 'admin' (it was a list that didn't include it)
ALTER TABLE users MODIFY role VARCHAR(20) NOT NULL DEFAULT 'student';
UPDATE users SET role = 'student' WHERE role = '' OR role IS NULL;
-- Make yourself the first admin (change the email):
-- UPDATE users SET role = 'admin' WHERE email = 'your@email.com';

-- 7) Personalized feedback and the AIMIS Coach chatbot (RAG)
-- Feedback for each answer: what was weak (quoting the student) and what a better answer adds
CREATE TABLE IF NOT EXISTS answer_feedback (
  response_id INT PRIMARY KEY,
  feedback TEXT,
  weak_quote TEXT,
  better_answer TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Sub-skill labels for each answer (e.g. Critical thinking = weak), so the chatbot can say exactly where
CREATE TABLE IF NOT EXISTS skill_labels (
  label_id INT AUTO_INCREMENT PRIMARY KEY,
  response_id INT NOT NULL,
  skill VARCHAR(40) NOT NULL,
  rating VARCHAR(10) NOT NULL,
  reason VARCHAR(300),
  INDEX idx_label_response (response_id),
  INDEX idx_label_skill (skill)
);
-- RAG knowledge base: small text pieces of each interview plus their embedding vectors
CREATE TABLE IF NOT EXISTS rag_chunks (
  chunk_id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  interview_id INT NOT NULL,
  response_id INT NULL,
  question_order INT NULL,
  kind VARCHAR(20) NOT NULL,
  content TEXT NOT NULL,
  embedding MEDIUMTEXT NULL,
  embed_model VARCHAR(80) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_chunk_user (user_id),
  INDEX idx_chunk_interview (interview_id)
);
-- Chatbot conversation history
CREATE TABLE IF NOT EXISTS chat_messages (
  message_id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  interview_id INT NULL,
  role VARCHAR(10) NOT NULL,
  content TEXT NOT NULL,
  sources TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_chat_user (user_id)
);
