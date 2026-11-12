-- 11) Adviser's flow: log in -> onboarding (What is AIMIS) -> data privacy consent -> dashboard.
-- Run this once in SQLyog on the aimis database (or run: python check_setup.py --fix, which does the same).
-- Safe on a database that already has data: it only adds columns. Existing students see the onboarding
-- and the consent page once, the next time they log in.

-- When the student finished the "What is AIMIS" onboarding
ALTER TABLE users ADD COLUMN onboarded_at DATETIME NULL;
-- The consent version the student agreed to, and when (NULL = not agreed yet or withdrawn)
ALTER TABLE users ADD COLUMN consent_version VARCHAR(10) NULL;
ALTER TABLE users ADD COLUMN consent_at DATETIME NULL;
