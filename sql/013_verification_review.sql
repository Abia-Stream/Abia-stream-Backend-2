-- 013_verification_review.sql
-- Manual ID review tools (`verification` app):
--   rejection_reason    - why an attempt was rejected, from a fixed list
--                         (verification/review.py); shown to the creator
--   checklist           - the reviewer's answers to the review checklist
--   documents_purged_at - when the private ID photos were deleted from
--                         Cloudinary (kept only VERIFICATION_DOCUMENT_RETENTION_DAYS
--                         after a decision; the decision record itself stays)
-- Additive and idempotent.

alter table verification_attempts
    add column if not exists rejection_reason    text        null,
    add column if not exists checklist           jsonb       null,
    add column if not exists documents_purged_at timestamptz null;

-- Finding decided attempts whose photos are due for deletion.
create index if not exists verification_attempts_purge_idx
    on verification_attempts (reviewed_at)
    where documents_purged_at is null
      and (document_public_id is not null or selfie_public_id is not null);
