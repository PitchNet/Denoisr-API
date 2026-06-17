-- Read receipts and reactions update silently (no error) when their tables
-- aren't in the supabase_realtime publication, so getMessages looks correct
-- on load but the "Seen" indicator and live reaction chips never appear
-- without a manual refresh. Add both tables to the publication.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime' AND tablename = 'conversation_participants'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE conversation_participants;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime' AND tablename = 'message_reactions'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE message_reactions;
  END IF;
END $$;

ALTER TABLE conversation_participants REPLICA IDENTITY FULL;
ALTER TABLE message_reactions REPLICA IDENTITY FULL;
