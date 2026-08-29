-- Billing owns refunds. It does NOT own the compensation ceiling: that is a
-- policy value held outside any single service. If Billing owned the ceiling it
-- would be the authoritative system for the aggregate, and the experiment would
-- collapse into a weaker single-system one.

CREATE TABLE IF NOT EXISTS refunds (
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

CREATE INDEX IF NOT EXISTS refunds_case_idx ON refunds (case_id);

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
