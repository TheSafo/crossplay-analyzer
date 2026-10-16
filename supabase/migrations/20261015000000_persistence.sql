-- Per-user game history and Quackle analysis snapshots.
-- All reads and writes go through the authenticated Vercel API. The credential
-- table is intentionally unavailable through the browser Data API.

create table if not exists public.nyt_credentials (
  user_id uuid primary key references auth.users (id) on delete cascade,
  ciphertext text not null,
  nonce text not null,
  key_version smallint not null default 1,
  updated_at timestamptz not null default now()
);

create table if not exists public.crossplay_games (
  user_id uuid not null references auth.users (id) on delete cascade,
  nyt_game_id text not null,
  summary jsonb not null,
  review jsonb,
  imported_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, nyt_game_id)
);

create index if not exists crossplay_games_user_updated_idx
  on public.crossplay_games (user_id, updated_at desc);

create table if not exists public.game_analyses (
  user_id uuid not null,
  nyt_game_id text not null,
  analysis_version text not null,
  win_trend jsonb,
  move_quality jsonb,
  updated_at timestamptz not null default now(),
  primary key (user_id, nyt_game_id, analysis_version),
  foreign key (user_id, nyt_game_id)
    references public.crossplay_games (user_id, nyt_game_id) on delete cascade
);

create index if not exists game_analyses_user_updated_idx
  on public.game_analyses (user_id, updated_at desc);

alter table public.nyt_credentials enable row level security;
alter table public.crossplay_games enable row level security;
alter table public.game_analyses enable row level security;

revoke all on public.nyt_credentials from anon, authenticated;
revoke all on public.crossplay_games from anon, authenticated;
revoke all on public.game_analyses from anon, authenticated;
grant all on public.nyt_credentials to service_role;
grant all on public.crossplay_games to service_role;
grant all on public.game_analyses to service_role;
