-- Adds a durable audit trail for edits to an already-saved QA score.
--
-- Editing a QA audit (the "Edit score" button in the QA form) has always
-- silently overwritten the row in qa_entries with no record of what the
-- score used to be, who changed it, or why — most often because a score
-- was disputed. This adds one append-only column that logs every edit.

alter table public.qa_entries
    add column if not exists edit_log jsonb not null default '[]'::jsonb;

comment on column public.qa_entries.edit_log is
    'Audit trail of edits made to an already-saved QA score. A fresh '
    'submission (no prior entry) leaves this empty — entries are only '
    'appended when an EXISTING audit is re-saved via "Edit score".
    Each element is an object:
      edited_at              -- UTC ISO timestamp of the edit
      edited_by              -- reviewer name who made the edit
      reason                 -- "Dispute", "Correction", or "Other"
      dispute_reason         -- required when reason is "Dispute"; what was
                                 disputed and why
      dispute_conclusion     -- optional; how the dispute was resolved,
                                 filled in once known (may be blank)
      previous_score         -- total_score before this edit
      previous_result        -- result before this edit
      previous_scores        -- per-rubric scores dict before this edit
      previous_remarks       -- per-rubric remarks dict before this edit
      previous_overall_comments
      previous_qa_reviewer
      previous_qa_date
    Never rewritten in place — each edit appends one more element, so the
    full history survives any number of later edits.';
