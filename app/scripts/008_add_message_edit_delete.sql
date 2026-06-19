-- Allow editing and soft-deleting messages
ALTER TABLE messages ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- UPDATE events (edit/delete) need to reach realtime subscribers the same way
-- INSERT events already do — see 004_enable_realtime_for_read_receipts.sql for why.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime' AND tablename = 'messages'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE messages;
  END IF;
END $$;

ALTER TABLE messages REPLICA IDENTITY FULL;
