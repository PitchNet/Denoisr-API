-- Companies currently have zero verification: any signed-in user can create
-- a company with any name/website and immediately post jobs. This adds a
-- manual-review status that admins set via AdminController; jobs are never
-- blocked on this, it only drives the "Unverified" badge shown elsewhere.

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (verification_status IN ('unverified', 'verified', 'rejected')),
  ADD COLUMN IF NOT EXISTS verification_notes TEXT,
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS verified_by UUID REFERENCES people(id);
