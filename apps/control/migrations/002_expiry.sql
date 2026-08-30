-- Bounded-time enforcement for reservations.
--
-- Without a deadline a hold taken by an agent that then dies is held forever:
-- budget occupied by nothing, and every later legitimate action refused. The
-- property that makes it dangerous is that the refusal looks EXACTLY like the
-- control working correctly, so nobody investigates. THREAT-MODEL.md T9.
--
-- EXPIRED is a distinct state, not a reuse of RELEASED. A hold the agent
-- released is a normal ending; a hold the reaper took back is evidence an agent
-- died mid-flight. Collapsing them makes the second invisible.
ALTER TABLE reservations ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

ALTER TABLE reservations DROP CONSTRAINT IF EXISTS reservations_state_check;
ALTER TABLE reservations ADD CONSTRAINT reservations_state_check
    CHECK (state IN ('HELD', 'COMMITTED', 'RELEASED', 'EXPIRED'));

-- Partial: only HELD rows are ever reaping candidates, and they are the
-- minority once a case settles.
CREATE INDEX IF NOT EXISTS reservations_due_idx
    ON reservations (expires_at) WHERE state = 'HELD';
