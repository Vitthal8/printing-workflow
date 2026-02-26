-- ═══════════════════════════════════════════════════════════════
-- PrintFlow Pro — Supabase Database Schema
-- Run this entire file in: Supabase → SQL Editor → New Query
-- ═══════════════════════════════════════════════════════════════

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── 1. Clients ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clients (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  company_name TEXT NOT NULL,
  contact_name TEXT,
  email        TEXT NOT NULL UNIQUE,
  phone        TEXT,
  gst_number   TEXT,
  is_active    BOOLEAN DEFAULT true,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── 2. Jobs ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  job_number       TEXT NOT NULL UNIQUE,
  client_id        UUID REFERENCES clients(id),
  job_type         TEXT CHECK (job_type IN ('simplex','duplex','multipage')) NOT NULL,
  quantity         INTEGER NOT NULL,
  pages_per_piece  INTEGER DEFAULT 1,
  variable_data    BOOLEAN DEFAULT false,
  dispatch_mode    TEXT CHECK (dispatch_mode IN ('ordinary','speed_ack','speed_no_ack','inland')) NOT NULL,
  fold             BOOLEAN DEFAULT false,
  insert           BOOLEAN DEFAULT false,
  sort             BOOLEAN DEFAULT false,
  status           TEXT DEFAULT 'new' CHECK (status IN (
                     'new','processing','approval','printing',
                     'postprint','franking','docket','dispatch','complete','error'
                   )),
  print_file_url   TEXT,
  data_file_url    TEXT,
  contact_name     TEXT,
  contact_email    TEXT,
  approval_token   TEXT,
  approved_at      TIMESTAMPTZ,
  approved_by      TEXT,
  proof_sent_at    TIMESTAMPTZ,
  record_count     INTEGER,
  validation_passed BOOLEAN,
  validation_errors JSONB,
  validation_warnings JSONB,
  notes            TEXT,
  received_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at       TIMESTAMPTZ DEFAULT NOW(),
  completed_at     TIMESTAMPTZ
);

-- ── 3. Dispatches ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dispatches (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  job_id            UUID REFERENCES jobs(id),
  dispatch_mode     TEXT NOT NULL,
  piece_count       INTEGER NOT NULL,
  fold_done         BOOLEAN DEFAULT false,
  insert_done       BOOLEAN DEFAULT false,
  sort_done         BOOLEAN DEFAULT false,
  frank_amount      NUMERIC(10,2),
  frank_confirmed   BOOLEAN DEFAULT false,
  franked_at        TIMESTAMPTZ,
  docket_id         UUID,                        -- set after docket is created
  tracking_reference TEXT,
  operator_id       UUID,
  dispatched_at     TIMESTAMPTZ DEFAULT NOW(),
  delivery_status   TEXT DEFAULT 'pending'
);

-- ── 4. Dockets ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dockets (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  docket_number  TEXT NOT NULL UNIQUE,
  job_id         UUID REFERENCES jobs(id),
  dispatch_id    UUID REFERENCES dispatches(id),
  total_pieces   INTEGER NOT NULL,
  dispatch_mode  TEXT NOT NULL,
  frank_amount   NUMERIC(10,2) NOT NULL,
  franked_at     TIMESTAMPTZ,
  generated_at   TIMESTAMPTZ DEFAULT NOW(),
  is_voided      BOOLEAN DEFAULT false,
  void_reason    TEXT
);

-- Add FK from dispatches to dockets
ALTER TABLE dispatches
  ADD CONSTRAINT fk_dispatch_docket
  FOREIGN KEY (docket_id) REFERENCES dockets(id)
  DEFERRABLE INITIALLY DEFERRED;

-- ── 5. Invoices ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invoices (
  id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  invoice_number       TEXT NOT NULL UNIQUE,
  client_id            UUID REFERENCES clients(id),
  job_id               UUID REFERENCES jobs(id),
  print_cost           NUMERIC(10,2) DEFAULT 0,
  data_processing_cost NUMERIC(10,2) DEFAULT 0,
  dispatch_cost        NUMERIC(10,2) DEFAULT 0,
  handling_cost        NUMERIC(10,2) DEFAULT 0,
  subtotal             NUMERIC(10,2) NOT NULL,
  gst_rate             NUMERIC(5,2) DEFAULT 18,
  gst_amount           NUMERIC(10,2) NOT NULL,
  total_amount         NUMERIC(10,2) NOT NULL,
  status               TEXT DEFAULT 'draft' CHECK (status IN ('draft','sent','paid','overdue','cancelled')),
  due_date             DATE,
  paid_at              TIMESTAMPTZ,
  created_at           TIMESTAMPTZ DEFAULT NOW()
);

-- ── 6. Activity Log ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activity_log (
  id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  job_id     UUID REFERENCES jobs(id),
  action     TEXT NOT NULL,
  details    TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Sequence + RPC for job numbers ───────────────────────────
CREATE SEQUENCE IF NOT EXISTS job_seq START 1;

CREATE OR REPLACE FUNCTION next_job_number()
RETURNS integer LANGUAGE sql AS
$$ SELECT nextval('job_seq')::integer $$;

-- ── Storage bucket ───────────────────────────────────────────
-- Run this in the Supabase Dashboard → Storage → New Bucket
-- Name: job-files, Private: YES

-- ── Sample data (optional, for testing) ──────────────────────
INSERT INTO clients (company_name, contact_name, email, phone) VALUES
  ('HDFC Bank Ltd.',    'Priya Sharma',  'hdfc@example.com', '9820000001'),
  ('LIC of India',      'Rajesh Patil',  'lic@example.com',  '9820000002'),
  ('SBI Cards',         'Anita Desai',   'sbi@example.com',  '9820000003')
ON CONFLICT (email) DO NOTHING;
