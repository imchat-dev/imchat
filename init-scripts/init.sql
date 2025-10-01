CREATE EXTENSION IF NOT EXISTS pgcrypto;       -- gen_random_uuid() icin
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- (opsiyonel) fuzzy aramalar

-- Sohbet oturumlari
CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR(64) NOT NULL,
  title TEXT,
  title_locked BOOLEAN DEFAULT FALSE,
  started_at TIMESTAMP DEFAULT now(),
  last_activity_at TIMESTAMP DEFAULT now(),
  client_ip TEXT,
  user_agent TEXT
);

CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  description TEXT,
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP
);

-- Access key tablosu
CREATE TABLE IF NOT EXISTS access_key (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  expire_date TIMESTAMP
);

-- Docs tablosu
CREATE TABLE IF NOT EXISTS docs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  filepath TEXT NOT NULL,
  name TEXT NOT NULL,
  ext VARCHAR(10) NOT NULL,
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP
);

-- Mesajlar
CREATE TABLE IF NOT EXISTS chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR(64) NOT NULL,
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
  message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
  score SMALLINT,
  reason TEXT,
  created_at TIMESTAMP DEFAULT now()
);

-- Hata/denetim kayitlari
CREATE TABLE IF NOT EXISTS errors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NULL REFERENCES tenants(id) ON DELETE SET NULL,
  session_id UUID NULL REFERENCES chat_sessions(id) ON DELETE SET NULL,
  message_id UUID NULL REFERENCES chat_messages(id) ON DELETE SET NULL,
  error_type TEXT,
  error_message TEXT,
  stack TEXT,
  created_at TIMESTAMP DEFAULT now()
);

-- MIGRASYON DUZELTMELERI
-- Update tenant_id columns to UUID with proper foreign keys
ALTER TABLE chat_sessions
  ADD COLUMN IF NOT EXISTS tenant_id_new UUID,
  ADD COLUMN IF NOT EXISTS title_locked BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- Add missing updated_at columns to match ORM
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;
ALTER TABLE docs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- Create a default tenant if it doesn't exist
INSERT INTO tenants (id, name, description, created_at)
SELECT gen_random_uuid(), 'default', 'Default tenant', now()
WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE name = 'default');

-- Update tenant_id to use UUID
UPDATE chat_sessions
SET tenant_id_new = (SELECT id FROM tenants WHERE name = 'default' LIMIT 1)
WHERE tenant_id_new IS NULL;

ALTER TABLE chat_sessions
  DROP COLUMN IF EXISTS tenant_id,
  DROP COLUMN IF EXISTS user_role,
  DROP COLUMN IF EXISTS profile_key;

ALTER TABLE chat_sessions
  RENAME COLUMN tenant_id_new TO tenant_id;

ALTER TABLE chat_sessions
  ALTER COLUMN tenant_id SET NOT NULL,
  ALTER COLUMN last_activity_at SET DEFAULT now(),
  ADD CONSTRAINT fk_chat_sessions_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

-- Update chat_messages tenant_id to UUID
ALTER TABLE chat_messages
  ADD COLUMN IF NOT EXISTS tenant_id_new UUID,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

UPDATE chat_messages m
SET tenant_id_new = s.tenant_id
FROM chat_sessions s
WHERE m.session_id = s.id
  AND m.tenant_id_new IS NULL;

ALTER TABLE chat_messages
  DROP COLUMN IF EXISTS tenant_id,
  DROP COLUMN IF EXISTS profile_key;

ALTER TABLE chat_messages
  RENAME COLUMN tenant_id_new TO tenant_id;

ALTER TABLE chat_messages
  ALTER COLUMN tenant_id SET NOT NULL,
  ADD CONSTRAINT fk_chat_messages_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

-- Update chat_history tenant_id to UUID
ALTER TABLE chat_history
  ADD COLUMN IF NOT EXISTS tenant_id_new UUID;

UPDATE chat_history h
SET tenant_id_new = s.tenant_id
FROM chat_sessions s
WHERE h.session_id = s.id
  AND h.tenant_id_new IS NULL;

ALTER TABLE chat_history
  DROP COLUMN IF EXISTS tenant_id,
  DROP COLUMN IF EXISTS user_role,
  DROP COLUMN IF EXISTS profile_key;

ALTER TABLE chat_history
  RENAME COLUMN tenant_id_new TO tenant_id;

ALTER TABLE chat_history
  ALTER COLUMN tenant_id SET NOT NULL,
  ADD CONSTRAINT fk_chat_history_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

-- Update chat_feedback tenant_id to UUID
ALTER TABLE chat_feedback
  ADD COLUMN IF NOT EXISTS tenant_id_new UUID;

UPDATE chat_feedback f
SET tenant_id_new = m.tenant_id
FROM chat_messages m
WHERE f.message_id = m.id
  AND f.tenant_id_new IS NULL;

ALTER TABLE chat_feedback
  DROP COLUMN IF EXISTS tenant_id,
  DROP COLUMN IF EXISTS profile_key;

ALTER TABLE chat_feedback
  RENAME COLUMN tenant_id_new TO tenant_id;

ALTER TABLE chat_feedback
  ALTER COLUMN tenant_id SET NOT NULL,
  ADD CONSTRAINT fk_chat_feedback_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_chat_feedback_message_id FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant_user ON chat_sessions(tenant_id, last_activity_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created ON chat_messages(tenant_id, session_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_chat_history_tenant_session ON chat_history(tenant_id, session_id);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_message ON chat_feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_title ON chat_sessions USING gin (to_tsvector('turkish', coalesce(title,'')));
CREATE INDEX IF NOT EXISTS idx_tenants_name ON tenants(name);
CREATE INDEX IF NOT EXISTS idx_docs_tenant ON docs(tenant_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_name_unique ON tenants(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_feedback_message_unique ON chat_feedback(message_id);