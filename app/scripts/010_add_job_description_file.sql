-- Job description document (PDF/DOCX), stored in the "files" Supabase Storage bucket
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_description_url TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_description_filename TEXT;
