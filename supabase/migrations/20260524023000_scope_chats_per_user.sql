/*
  # Scope chats per user

  Before this migration the `chats` table had no owner column and the RLS
  policies allowed everything (`USING (true)`), so any caller could read or
  modify any chat. This migration:

    1. Wipes existing rows (already exposed cross-user; no integrity to keep).
    2. Adds chats.user_id (FK auth.users, cascade delete) + indexes.
    3. Replaces the permissive RLS policies with per-user policies, including
       message access via the parent chat's owner.

  The backend uses the Supabase service-role key so it bypasses RLS, but it
  enforces user_id in WHERE clauses on every query. RLS is the defense in
  depth in case anything else ever talks to these tables.
*/

-- 1. wipe orphan rows
DELETE FROM messages;
DELETE FROM chats;

-- 2. add user_id + indexes
ALTER TABLE chats
  ADD COLUMN user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_chats_user_id ON chats(user_id);
CREATE INDEX IF NOT EXISTS idx_chats_user_updated ON chats(user_id, updated_at DESC);

-- 3. drop permissive policies
DROP POLICY IF EXISTS "Allow all operations on chats"    ON chats;
DROP POLICY IF EXISTS "Allow all operations on messages" ON messages;

-- per-user policies on chats
CREATE POLICY "chats_select_own" ON chats
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "chats_insert_own" ON chats
  FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "chats_update_own" ON chats
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "chats_delete_own" ON chats
  FOR DELETE USING (auth.uid() = user_id);

-- messages inherit access via parent chat
CREATE POLICY "messages_select_via_chat" ON messages
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM chats WHERE chats.id = messages.chat_id AND chats.user_id = auth.uid())
  );
CREATE POLICY "messages_insert_via_chat" ON messages
  FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM chats WHERE chats.id = messages.chat_id AND chats.user_id = auth.uid())
  );
CREATE POLICY "messages_delete_via_chat" ON messages
  FOR DELETE USING (
    EXISTS (SELECT 1 FROM chats WHERE chats.id = messages.chat_id AND chats.user_id = auth.uid())
  );
