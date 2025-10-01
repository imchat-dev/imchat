CREATE EXTENSION IF NOT EXISTS pgcrypto;       -- gen_random_uuid() icin
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- (opsiyonel) fuzzy aramalar

-- Sohbet oturumlari
CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR(64) NOT NULL,
  profile_key VARCHAR(64) NOT NULL,
  user_id VARCHAR(50) NOT NULL,
  title TEXT,
  title_locked BOOLEAN DEFAULT FALSE,
  started_at TIMESTAMP DEFAULT now(),
  last_activity_at TIMESTAMP DEFAULT now(),
  client_ip TEXT,
  user_agent TEXT
);

-- Mesajlar
CREATE TABLE IF NOT EXISTS chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR(64) NOT NULL,
  profile_key VARCHAR(64) NOT NULL,
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  message_role VARCHAR(16) NOT NULL,
  content TEXT NOT NULL,
  model TEXT,
  latency_ms INT,
  prompt_tokens INT,
  completion_tokens INT,
  total_tokens INT,
  created_at TIMESTAMP DEFAULT now()
);

-- Gecmis kayitlari
CREATE TABLE IF NOT EXISTS chat_history (
  id SERIAL PRIMARY KEY,
  tenant_id VARCHAR(64) NOT NULL,
  profile_key VARCHAR(64) NOT NULL,
  user_id VARCHAR(50) NOT NULL,
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  request_id TEXT NOT NULL,
  ip TEXT NOT NULL,
  user_agent TEXT NOT NULL,
  model TEXT,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  latency_ms INT,
  prompt_tokens INT,
  completion_tokens INT,
  total_tokens INT
);

-- Geri bildirimler
CREATE TABLE IF NOT EXISTS chat_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR(64) NOT NULL,
  profile_key VARCHAR(64) NOT NULL,
  message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
  score SMALLINT,
  reason TEXT,
  created_at TIMESTAMP DEFAULT now()
);

-- Hata/denetim kayitlari
CREATE TABLE IF NOT EXISTS errors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR(64),
  profile_key VARCHAR(64),
  session_id UUID NULL REFERENCES chat_sessions(id) ON DELETE SET NULL,
  message_id UUID NULL REFERENCES chat_messages(id) ON DELETE SET NULL,
  error_type TEXT,
  error_message TEXT,
  stack TEXT,
  created_at TIMESTAMP DEFAULT now()
);

-- MIGRASYON DUZELTMELERI
ALTER TABLE chat_sessions
  ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS profile_key VARCHAR(64),
  ADD COLUMN IF NOT EXISTS title_locked BOOLEAN DEFAULT FALSE;

UPDATE chat_sessions
SET tenant_id = COALESCE(tenant_id, 'pilot')
WHERE tenant_id IS NULL;

UPDATE chat_sessions
SET profile_key = COALESCE(profile_key, 'default')
WHERE profile_key IS NULL;

ALTER TABLE chat_sessions
  ALTER COLUMN tenant_id SET DEFAULT 'pilot',
  ALTER COLUMN tenant_id SET NOT NULL,
  ALTER COLUMN profile_key SET DEFAULT 'default',
  ALTER COLUMN profile_key SET NOT NULL,
  ALTER COLUMN last_activity_at SET DEFAULT now();

ALTER TABLE chat_sessions
  DROP COLUMN IF EXISTS user_role;

ALTER TABLE chat_messages
  ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS profile_key VARCHAR(64);

UPDATE chat_messages m
SET tenant_id = COALESCE(m.tenant_id, s.tenant_id),
    profile_key = COALESCE(m.profile_key, s.profile_key)
FROM chat_sessions s
WHERE m.session_id = s.id
  AND (m.tenant_id IS NULL OR m.profile_key IS NULL);

ALTER TABLE chat_messages
  ALTER COLUMN tenant_id SET NOT NULL,
  ALTER COLUMN profile_key SET NOT NULL;

ALTER TABLE chat_history
  ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS profile_key VARCHAR(64);

UPDATE chat_history h
SET tenant_id = COALESCE(h.tenant_id, s.tenant_id),
    profile_key = COALESCE(h.profile_key, s.profile_key)
FROM chat_sessions s
WHERE h.session_id = s.id
  AND (h.tenant_id IS NULL OR h.profile_key IS NULL);

ALTER TABLE chat_history
  ALTER COLUMN tenant_id SET NOT NULL,
  ALTER COLUMN profile_key SET NOT NULL;

ALTER TABLE chat_history
  DROP COLUMN IF EXISTS user_role;

ALTER TABLE chat_feedback
  ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS profile_key VARCHAR(64);

UPDATE chat_feedback f
SET tenant_id = COALESCE(f.tenant_id, m.tenant_id),
    profile_key = COALESCE(f.profile_key, m.profile_key)
FROM chat_messages m
WHERE f.message_id = m.id
  AND (f.tenant_id IS NULL OR f.profile_key IS NULL);

ALTER TABLE chat_feedback
  ALTER COLUMN tenant_id SET NOT NULL,
  ALTER COLUMN profile_key SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant_user ON chat_sessions(tenant_id, profile_key, user_id, last_activity_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created ON chat_messages(tenant_id, profile_key, session_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_chat_history_tenant_session ON chat_history(tenant_id, profile_key, session_id);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_message ON chat_feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_title ON chat_sessions USING gin (to_tsvector('turkish', coalesce(title,'')));
