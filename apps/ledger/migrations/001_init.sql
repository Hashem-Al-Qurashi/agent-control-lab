-- Ledger owns credits. It does NOT own the compensation ceiling: that is a
-- policy value held outside any single service. If Ledger owned the ceiling it
-- would be the authoritative system for the aggregate, and the experiment would
-- collapse into a weaker single-system one.

CREATE TABLE IF NOT EXISTS credits (
    id              BIGSERIAL PRIMARY KEY,
    case_id         TEXT           NOT NULL,
    actor_id        TEXT           NOT NULL,
    idempotency_key TEXT           NOT NULL UNIQUE,
    -- NUMERIC, never float. Money compared against a ceiling cannot carry
    -- binary floating point error.
    amount          NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    state           TEXT           NOT NULL
                    CHECK (state IN ('PENDING', 'COMMITTED', 'SETTLED', 'VOIDED')),
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS credits_case_idx ON credits (case_id);

-- Append-only transition log. Built now even though Stage 0's oracle reads SQL
-- at a quiescence gate: later modes have no quiescence point, and history
-- cannot be reconstructed from mutable rows, so this cannot be retrofitted.
CREATE TABLE IF NOT EXISTS decision_log (
    id         BIGSERIAL PRIMARY KEY,
    case_id    TEXT        NOT NULL,
    sequence   BIGINT      NOT NULL,
    actor_id   TEXT        NOT NULL,
    service    TEXT        NOT NULL,
    entity_id  BIGINT,
    from_state TEXT,
    to_state   TEXT        NOT NULL,
    amount     NUMERIC(12, 2),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (case_id, sequence)
);

-- Server-side request timing. Evidence that two actors were genuinely in flight
-- at once, rather than the client merely believing so. Without this, a server
-- that quietly serialises requests would make P2 execute as P1 and read as the
-- thesis being false.
CREATE TABLE IF NOT EXISTS request_log (
    id         BIGSERIAL PRIMARY KEY,
    actor_id   TEXT,
    schedule_id TEXT,
    method     TEXT        NOT NULL,
    path       TEXT        NOT NULL,
    pid        INTEGER     NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at   TIMESTAMPTZ
);

-- Transactional outbox. Written in the same transaction as the effect it
-- describes, so propagation lag is a property of the architecture rather than a
-- bug in the harness. Per-service, because there is no shared transaction
-- boundary to put it anywhere else -- which is the premise, not an inconvenience.
CREATE TABLE IF NOT EXISTS outbox (
    id           BIGSERIAL PRIMARY KEY,
    case_id      TEXT           NOT NULL,
    actor_id     TEXT           NOT NULL,
    service      TEXT           NOT NULL,
    event_type   TEXT           NOT NULL,
    entity_id    BIGINT         NOT NULL,
    amount       NUMERIC(12, 2) NOT NULL,
    published_at TIMESTAMPTZ    NOT NULL DEFAULT now(),
    applied_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS outbox_unapplied_idx ON outbox (id) WHERE applied_at IS NULL;
