-- 006_video_delivery_type.sql
-- Records how each video asset is stored in Cloudinary:
--   'upload'         public delivery; anyone with the URL can fetch it
--   'authenticated'  only signed URLs work (non-public videos)
--
-- Every existing row is 'upload', which is exactly how they were uploaded, so
-- this changes nothing for current videos. Additive and idempotent.

alter table videos
    add column if not exists cloudinary_delivery_type varchar(20)
    not null default 'upload';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'videos_cloudinary_delivery_type_check'
    ) then
        alter table videos
            add constraint videos_cloudinary_delivery_type_check
            check (cloudinary_delivery_type in ('upload', 'authenticated'));
    end if;
end $$;
