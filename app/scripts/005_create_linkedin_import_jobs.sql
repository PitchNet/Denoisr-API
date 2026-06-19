-- Run this once in the Supabase SQL editor (no migration tooling exists in this repo yet).
create table linkedin_import_jobs (
  id              uuid primary key default gen_random_uuid(),
  linkedin_url    text not null,
  status          text not null default 'scraped'
                  check (status in ('scraped', 'structured', 'failed')),
  raw_data        jsonb not null,
  profile_picture text,
  result          jsonb,
  error           text,
  attempt_count   int not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index linkedin_import_jobs_created_at_idx on linkedin_import_jobs (created_at);
