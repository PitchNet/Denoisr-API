# Security — Secret Remediation Runbook

> **Status: ACTION REQUIRED (not yet executed).** This file documents the steps; run them yourself
> when ready. Key rotation is irreversible/operational, so it is intentionally left manual.

## Exposure

`Denoisr-API/` is a git repository that contains live secrets:

- `.env` — listed in `.gitignore`, but was committed before being ignored, so it is in history.
- `private_key.pem` / `public_key.pem` — **not** ignored at all.

Exposed values include: `SECRET_KEY`, `SUPABASE_KEY` (service role), `APIFY_TOKEN`,
`GOOGLE_API_KEY`, `RESEND_API_KEY`, and the `VAPID_PRIVATE_KEY` (the `.pem` pair).

## Remediation

```bash
# From inside Denoisr-API/

# 1. Stop tracking the secret files (.env is already in .gitignore)
printf '\n*.pem\n' >> .gitignore
git rm --cached .env private_key.pem public_key.pem

# 2. Commit the removal
git commit -m "Stop tracking secrets; rotate keys"

# 3. ROTATE every exposed credential at its provider — the old values are public in git history,
#    so simply un-tracking them is not enough:
#      - SECRET_KEY        (regenerate; invalidates existing JWTs — users re-login)
#      - SUPABASE_KEY      (rotate service-role key in Supabase dashboard)
#      - APIFY_TOKEN       (Apify account)
#      - GOOGLE_API_KEY    (Google AI Studio / Cloud console)
#      - RESEND_API_KEY    (Resend dashboard)
#      - VAPID key pair    (regenerate: `python3 -m py_vapid`)
#    Then update the new values in Render's environment settings.

# 4. Purge the old values from git history (rewrites history — coordinate with collaborators first):
#    git filter-repo --invert-paths --path .env --path private_key.pem --path public_key.pem
#    # or use BFG Repo-Cleaner
#    then force-push the rewritten history.
```

Step 3 (rotation) is what actually closes the exposure; steps 1, 2, and 4 only stop future leakage.
