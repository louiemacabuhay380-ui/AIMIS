-- 8) Specific feedback, item by item: each item points to one answer, quotes the student, and gives a fix
CREATE TABLE IF NOT EXISTS feedback_items (
  item_id INT AUTO_INCREMENT PRIMARY KEY,
  interview_id INT NOT NULL,
  kind VARCHAR(12) NOT NULL,      -- strength / improve / delivery / progress / next
  answer_no INT NULL,             -- which answer it is about (Answer 1, 2, 3 ...)
  point TEXT,                     -- what was good or weak
  quote TEXT,                     -- the student's own words
  fix TEXT,                       -- what to do differently
  example TEXT,                   -- how they could say it
  sort_order INT NOT NULL DEFAULT 0,
  INDEX idx_item_interview (interview_id)
);
