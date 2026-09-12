-- ============================================================
-- Fix legacy study_area codes on students left behind by the
-- General Arts 1-6(A/B) -> General Arts A-K rename.
-- Mapping taken directly from the admin's rename document.
-- Safe to run as-is: each old code maps to exactly one new code.
-- ============================================================

BEGIN;

UPDATE students SET study_area = 'general_arts_a' WHERE study_area = 'general_arts__1';
UPDATE students SET study_area = 'general_arts_c' WHERE study_area = 'general_arts__2';
UPDATE students SET study_area = 'general_arts_d' WHERE study_area = 'general_arts__3__a';
UPDATE students SET study_area = 'general_arts_e' WHERE study_area = 'general_arts__3__b';
UPDATE students SET study_area = 'general_arts_f' WHERE study_area = 'general_arts__4__a';
UPDATE students SET study_area = 'general_arts_g' WHERE study_area = 'general_arts__4__b';
UPDATE students SET study_area = 'general_arts_h' WHERE study_area = 'general_arts__5__a';
UPDATE students SET study_area = 'general_arts_i' WHERE study_area = 'general_arts__5__b';
UPDATE students SET study_area = 'general_arts_j' WHERE study_area = 'general_arts__6__a';
UPDATE students SET study_area = 'general_arts_k' WHERE study_area = 'general_arts__6__b';

-- Sanity check before committing: this should return ZERO rows.
-- If it doesn't, some other legacy code slipped through — roll back
-- and check what it found before re-running.
SELECT class_name, study_area, COUNT(*)
FROM students
WHERE study_area LIKE 'general_arts\_\_%' ESCAPE '\'
GROUP BY class_name, study_area;

COMMIT;
-- If the sanity-check SELECT above returned rows, run ROLLBACK; instead
-- of COMMIT, fix the mapping, and re-run.


-- ============================================================
-- These CANNOT be auto-mapped — a person has to pick the right
-- current code for each student. Run this to get the worklist.
-- ============================================================
SELECT id, first_name, last_name, class_name, study_area
FROM students
WHERE study_area IN ('business_c', 'visual_performing_arts', 'none')
   OR study_area IS NULL
ORDER BY class_name, study_area, last_name;

-- business_c        -> Business C/D was removed entirely. Pick business_a or business_b
--                      based on which electives that student is actually taking.
-- visual_performing_arts (no suffix) -> pick visual_performing_arts_a or _b the same way.
-- none / NULL       -> student was never assigned a track at all; assign one.
