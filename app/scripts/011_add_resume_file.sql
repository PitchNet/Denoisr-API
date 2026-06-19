-- Resume document (PDF/DOCX), stored in the "files" Supabase Storage bucket
ALTER TABLE people ADD COLUMN IF NOT EXISTS resume_url TEXT;
ALTER TABLE people ADD COLUMN IF NOT EXISTS resume_filename TEXT;
