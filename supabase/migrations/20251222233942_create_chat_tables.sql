/*
  # Create Chat Tables

  1. New Tables
    - `chats`
      - `id` (uuid, primary key) - Unique identifier for each chat thread
      - `title` (text) - Chat title/summary
      - `created_at` (timestamptz) - When the chat was created
      - `updated_at` (timestamptz) - Last update time
    
    - `messages`
      - `id` (uuid, primary key) - Unique identifier for each message
      - `chat_id` (uuid, foreign key) - References chats table
      - `role` (text) - Message role (user, assistant, system)
      - `content` (text) - Message content
      - `created_at` (timestamptz) - When the message was created
  
  2. Security
    - Enable RLS on both tables
    - For now, allow all operations (can be restricted later with auth)
  
  3. Indexes
    - Index on chat_id in messages table for faster queries
    - Index on created_at for sorting
*/

CREATE TABLE IF NOT EXISTS chats (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title text NOT NULL DEFAULT 'New Chat',
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  chat_id uuid NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role text NOT NULL,
  content text NOT NULL,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_chats_created_at ON chats(created_at DESC);

ALTER TABLE chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all operations on chats"
  ON chats
  FOR ALL
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Allow all operations on messages"
  ON messages
  FOR ALL
  USING (true)
  WITH CHECK (true);
