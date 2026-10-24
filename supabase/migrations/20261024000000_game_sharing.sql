-- Opaque links grant read access to one completed review through the server.
-- Existing RLS and service-role-only grants keep the table private.
alter table public.crossplay_games
  add column if not exists share_token text;

create unique index if not exists crossplay_games_share_token_idx
  on public.crossplay_games (share_token);
