-- Lets a team lead submit a question/dispute on an agent's behalf from the
-- Team Lead Dashboard's drill-down. The dispute is still recorded against
-- the agent (same agent_id/agent_name as an agent's own submission) --
-- submitted_by just notes who actually filed it, shown to both the agent
-- (My Dashboard) and the reviewer (Questions & Disputes). NULL means the
-- agent submitted it themselves, same as every dispute before this
-- migration. New installs don't need this -- sql/schema.sql already
-- includes the column.

alter table disputes add column if not exists submitted_by text;
