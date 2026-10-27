-- Migration 005 only checks existing rows; a constraint cannot be un-validated. To go back past it, run the
-- down script of 004, which drops the constraint. This file exists so every migration has a down path.
SELECT 'nothing to undo: run down/004 to drop the constraint' AS note;
