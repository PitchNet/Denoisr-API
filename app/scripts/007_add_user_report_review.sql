-- user_reports was purely append-only (no admin ever reviews them). Add a
-- review state so AdminController can list open reports and mark them
-- dismissed/resolved, mirroring the companies.verification_status pattern.

ALTER TABLE user_reports
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'resolved', 'dismissed')),
  ADD COLUMN IF NOT EXISTS resolution_notes TEXT,
  ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS resolved_by UUID REFERENCES people(id);
