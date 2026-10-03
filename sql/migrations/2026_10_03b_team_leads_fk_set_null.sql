-- Follow-up to 2026_10_03_add_team_leads.sql, needed only if you already ran
-- that one: changes agents.team_lead_id's foreign key so deleting a team
-- lead (now possible from QA Log → Manage team leads → "Remove a team
-- lead") automatically clears that column on their agents instead of
-- failing with a foreign-key error. New installs don't need this —
-- sql/schema.sql already creates the column with this behavior.
--
-- agents_team_lead_id_fkey is the default constraint name Postgres assigns
-- to an inline "references" column constraint (<table>_<column>_fkey); if
-- you renamed it, adjust the name below to match.

alter table agents drop constraint if exists agents_team_lead_id_fkey;
alter table agents add constraint agents_team_lead_id_fkey
    foreign key (team_lead_id) references team_leads(id) on delete set null;
