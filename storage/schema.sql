-- RealReel simplified storage/database schema for Supabase SQL Editor.
-- Paste this file into Supabase Dashboard > SQL Editor and run it once.

create extension if not exists vector;
create extension if not exists pgcrypto;

do $$
begin
  create type video_platform as enum (
    'youtube',
    'tiktok',
    'instagram',
    'x',
    'facebook',
    'direct_upload',
    'unknown'
  );
exception
  when duplicate_object then null;
end $$;

create table if not exists public.videos (
  id uuid primary key default gen_random_uuid(),
  original_url text not null unique,
  platform video_platform not null default 'unknown',
  title text,
  uploader_handle varchar(255),
  uploader_url text,
  raw_video_path text,
  thumbnail_path text,
  transcript_path text,
  transcript_text text,
  duration_seconds numeric(10, 3),
  platform_upload_date date,
  file_sha256 varchar(64) unique,
  video_embedding vector(512),
  embedding_model varchar(128),
  ai_generated_score numeric(5, 4) not null check (
    ai_generated_score >= 0 and ai_generated_score <= 1
  ),
  misleading_context_score numeric(5, 4) not null check (
    misleading_context_score >= 0 and misleading_context_score <= 1
  ),
  repost_probability numeric(5, 4) not null check (
    repost_probability >= 0 and repost_probability <= 1
  ),
  credibility_score numeric(5, 4) not null check (
    credibility_score >= 0 and credibility_score <= 1
  ),
  overall_risk_score numeric(5, 4) not null check (
    overall_risk_score >= 0 and overall_risk_score <= 1
  ),
  -- overall_risk_score = max(misleading, visual, thumbnail, repost)
  -- ai_generated_score stores visual authenticity risk
  -- misleading_context_score stores misleading probability
  -- credibility_score stores 1 - overall_risk_score
  confidence numeric(5, 4) not null check (
    confidence >= 0 and confidence <= 1
  ),
  reasons jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_videos_platform
  on public.videos (platform);
create index if not exists ix_videos_file_sha256
  on public.videos (file_sha256);
create index if not exists ix_videos_created_at
  on public.videos (created_at);
create index if not exists ix_videos_platform_upload_date
  on public.videos (platform_upload_date);
create index if not exists ix_videos_video_embedding_hnsw
  on public.videos using hnsw (video_embedding vector_cosine_ops);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_videos_updated_at on public.videos;
create trigger set_videos_updated_at
before update on public.videos
for each row
execute function public.set_updated_at();

-- Keep buckets private. The backend uploads with the service-role key and
-- returns short-lived signed URLs to the frontend.
insert into storage.buckets (id, name, public)
values
  ('raw-videos', 'raw-videos', false),
  ('audio', 'audio', false),
  ('transcripts', 'transcripts', false),
  ('thumbnails', 'thumbnails', false),
  ('analysis', 'analysis', false)
on conflict (id) do update set public = excluded.public;

do $$
begin
  create type feedback_label as enum ('Correct', 'Incorrect');
exception
  when duplicate_object then null;
end $$;

create table if not exists public.analysis_feedback (
  id uuid primary key default gen_random_uuid(),
  vid_id text not null,
  label feedback_label not null,
  comment text,
  created_at timestamptz not null default now()
);

create index if not exists ix_analysis_feedback_vid_id
  on public.analysis_feedback (vid_id);
create index if not exists ix_analysis_feedback_created_at
  on public.analysis_feedback (created_at);
