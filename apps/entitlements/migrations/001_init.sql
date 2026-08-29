-- Entitlements owns feature grants. It does NOT own the plan -- that is a
-- billing concept, in Billing's database.
--
-- That split is the whole point. The invariant "every granted feature is
-- permitted by the current plan" spans two independently-owned systems, exactly
-- like the compensation ceiling, but involves no arithmetic at all.
CREATE TABLE IF NOT EXISTS feature_grants (
    id              BIGSERIAL PRIMARY KEY,
    case_id         TEXT        NOT NULL,
    actor_id        TEXT        NOT NULL,
    idempotency_key TEXT        NOT NULL UNIQUE,
    feature         TEXT        NOT NULL,
    state           TEXT        NOT NULL
                    CHECK (state IN ('GRANTED', 'REVOKED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS feature_grants_case_idx ON feature_grants (case_id);

CREATE TABLE IF NOT EXISTS request_log (
    id          BIGSERIAL PRIMARY KEY,
    actor_id    TEXT,
    schedule_id TEXT,
    method      TEXT        NOT NULL,
    path        TEXT        NOT NULL,
    pid         INTEGER     NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ
);
