-- 0002_drop_conversation_audit — remove the unused conversation/audit tables.
--
-- These were designed in 0001 but never wired: conversation storage is owned by
-- the Message Center, not this system. Dropped to keep the schema honest.
--
-- The `escalations` table is included here too. When the escalate-to-human tool
-- is built, its own migration will (re)create exactly the escalations table that
-- feature needs — the table appears with the feature, not before it.
--
-- Drop order respects the foreign keys (children before parents).

DROP TABLE IF EXISTS jacob.escalations;
DROP TABLE IF EXISTS jacob.turn_sources;
DROP TABLE IF EXISTS jacob.turns;
DROP TABLE IF EXISTS jacob.conversations;
