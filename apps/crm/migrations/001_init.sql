-- CRM holds a PROJECTION of compensation, not an authoritative record.
--
-- This is the point of Stage 1. In real systems an agent frequently cannot
-- query the authoritative store -- it reads a CRM or a reporting view, because
-- that is the integration point it was given. The projection lags, and the
-- agent's view is stale through no fault of its own diligence.
--
-- The lag is honest: it exists because events are applied asynchronously, not
-- because the harness inserted a sleep.
CREATE TABLE IF NOT EXISTS compensation_projection (
    case_id        TEXT PRIMARY KEY,
    total          NUMERIC(12, 2) NOT NULL DEFAULT 0,
    events_applied INTEGER        NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ    NOT NULL DEFAULT now()
);

-- Which source events this projection has already folded in. Keyed by the
-- originating service and its event id, so re-delivery cannot double-count --
-- a projection that double-counts would fabricate a violation.
CREATE TABLE IF NOT EXISTS applied_events (
    source_service TEXT   NOT NULL,
    source_id      BIGINT NOT NULL,
    case_id        TEXT   NOT NULL,
    amount         NUMERIC(12, 2) NOT NULL,
    applied_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_service, source_id)
);

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
