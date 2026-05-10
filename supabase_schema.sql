-- ═══════════════════════════════════════════════════
-- AgentMesh — Supabase Database Schema
-- ═══════════════════════════════════════════════════

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── Agents Table ───
CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    capabilities TEXT[] NOT NULL DEFAULT '{}',
    price_per_request INTEGER NOT NULL DEFAULT 0,
    wallet_address TEXT NOT NULL DEFAULT '',
    public_key TEXT NOT NULL DEFAULT '',
    reputation_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    completed_jobs INTEGER NOT NULL DEFAULT 0,
    total_jobs INTEGER NOT NULL DEFAULT 0,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Auctions Table ───
CREATE TABLE IF NOT EXISTS auctions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    requester_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    task TEXT NOT NULL,
    required_capability TEXT NOT NULL,
    budget INTEGER NOT NULL DEFAULT 0,
    deadline INTEGER NOT NULL DEFAULT 30,
    auction_duration INTEGER NOT NULL DEFAULT 10,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'awarded', 'expired')),
    bids JSONB NOT NULL DEFAULT '[]',
    winner JSONB,
    created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    closed_at DOUBLE PRECISION
);

-- ─── Jobs Table ───
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    auction_id UUID NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
    task TEXT NOT NULL,
    requester_id TEXT NOT NULL DEFAULT '',
    worker_id TEXT NOT NULL DEFAULT '',
    worker_name TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'paid')),
    result JSONB,
    payment_tx TEXT,
    created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    completed_at DOUBLE PRECISION,
    paid_at DOUBLE PRECISION
);

-- ─── Indexes for performance ───
CREATE INDEX IF NOT EXISTS idx_agents_capabilities ON agents USING GIN (capabilities);
CREATE INDEX IF NOT EXISTS idx_auctions_status ON auctions (status);
CREATE INDEX IF NOT EXISTS idx_auctions_requester ON auctions (requester_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_auction ON jobs (auction_id);

-- ─── RLS Policies (public access for development) ───
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE auctions ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

-- Allow all operations for service role (backend uses service key)
CREATE POLICY "Allow all for service role" ON agents FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for service role" ON auctions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for service role" ON jobs FOR ALL USING (true) WITH CHECK (true);
