-- Reply-to-message: a message can quote one earlier message in the same conversation
ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_id UUID REFERENCES messages(id) ON DELETE SET NULL;
