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
