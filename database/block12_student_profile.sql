-- 12) Onboarding profile ("know your student"): asked right after logging in for the first time, before the consent.
-- Run this once in SQLyog on the aimis database (or run: python check_setup.py --fix, which does the same).
-- Safe on a database that already has data: it only adds columns.
-- The AI interviewer uses these only to fit its questions to the student; they are never used for scoring.
ALTER TABLE users ADD COLUMN age TINYINT NULL;
ALTER TABLE users ADD COLUMN education_status VARCHAR(40) NULL;      -- e.g. College student, Fresh graduate
ALTER TABLE users ADD COLUMN course VARCHAR(100) NULL;               -- e.g. BS Information Technology
ALTER TABLE users ADD COLUMN year_level VARCHAR(20) NULL;            -- college students only
ALTER TABLE users ADD COLUMN work_experience VARCHAR(20) NULL;       -- none / ojt / part_time / full_time
ALTER TABLE users ADD COLUMN interview_experience VARCHAR(20) NULL;  -- never / few / many
ALTER TABLE users ADD COLUMN interview_confidence TINYINT NULL;      -- 1-4 (no neutral)
ALTER TABLE users ADD COLUMN focus_areas VARCHAR(255) NULL;          -- up to 3, separated by |
