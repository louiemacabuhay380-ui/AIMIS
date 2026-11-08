-- 9) Validation: human raters (teachers / HR) score the same answers as the AI, to measure agreement
CREATE TABLE IF NOT EXISTS human_ratings (
  rating_id INT AUTO_INCREMENT PRIMARY KEY,
  response_id INT NOT NULL,
  rater_id INT NOT NULL,                 -- users.user_id of an account with role 'rater'
  relevance TINYINT NOT NULL,            -- 1 to 5 rubric
  clarity TINYINT NOT NULL,
  completeness TINYINT NOT NULL,
  grammar TINYINT NOT NULL,
  comment VARCHAR(500) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_rating (response_id, rater_id),
  INDEX idx_rating_rater (rater_id)
);
