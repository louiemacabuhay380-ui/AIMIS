-- 10) Panel revisions: career goal, career-based and live questions, follow-up questions,
--     and the two-score rubric (Answer Effectiveness + Communication Delivery).
-- Run this once in SQLyog on the aimis database (or run: python check_setup.py --fix, which does the same).
-- Safe to run on a database that already has data: it only adds columns.

-- Career goal the student picks after creating an account (panel comments 5-6)
ALTER TABLE users ADD COLUMN career_goal VARCHAR(80) NULL;
-- The career goal at the time of each interview (so old reports stay correct if the student changes it)
ALTER TABLE interviews ADD COLUMN career_goal VARCHAR(80) NULL;
-- Questions for one career only (NULL = general question for any job).
-- source / review_status 'live' = written by the AI for one student's interview,
-- 'followup' = a follow-up the interviewer asked about a student's answer.
ALTER TABLE question_bank ADD COLUMN career_track VARCHAR(80) NULL;

-- Follow-up questions (panel comment 8): a follow-up points to the question it follows
ALTER TABLE interview_questions ADD COLUMN parent_iq_id INT NULL;

-- Rubric v2 (panel comments 10-12): two new answer criteria
ALTER TABLE nlp_analysis ADD COLUMN directness_score DECIMAL(5,2) NULL;
ALTER TABLE nlp_analysis ADD COLUMN specificity_score DECIMAL(5,2) NULL;
-- response_quality_score now = Answer Effectiveness, speech_performance_score = verbal delivery,
-- behavioral_score = nonverbal delivery. New: the combined delivery score and the performance profile.
ALTER TABLE evaluations ADD COLUMN delivery_score DECIMAL(5,2) NULL;
ALTER TABLE evaluations ADD COLUMN performance_profile VARCHAR(20) NULL;
ALTER TABLE evaluations ADD COLUMN rubric_version VARCHAR(10) NULL;

-- Human evaluators use the same criteria as the AI
ALTER TABLE human_ratings ADD COLUMN directness TINYINT NULL;
ALTER TABLE human_ratings ADD COLUMN specificity TINYINT NULL;
ALTER TABLE human_ratings MODIFY clarity TINYINT NULL;      -- no longer rated (kept for older ratings)
