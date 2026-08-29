-- Reservations against the compensation budget.
--
-- This is the coordination primitive P0 introduces: a single authority that can
-- see the aggregate, which neither Billing nor Ledger can. Its existence is the
-- whole contrast -- the same diligent policy, given this interface, does not
-- breach the ceiling.
CREATE TABLE IF NOT EXISTS reservations (
    id              BIGSERIAL PRIMARY KEY,
    case_id         TEXT           NOT NULL,
    actor_id        TEXT           NOT NULL,
    idempotency_key TEXT           NOT NULL UNIQUE,
    amount          NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    state           TEXT           NOT NULL
                    CHECK (state IN ('HELD', 'COMMITTED', 'RELEASED')),
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reservations_case_idx ON reservations (case_id);

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
