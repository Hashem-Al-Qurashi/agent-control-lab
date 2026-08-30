"""Time from breach to the reconciler noticing it -- including when it never does.

The most load-bearing claim in this repository is a NULL result: ordinary
reconciliation does not detect the aggregate breach. A null result from a broken
instrument is indistinguishable from a null result from a real absence, so this
module is calibrated the same way the oracle is -- against a defect the
reconciler genuinely catches. If the calibration case comes back undetected, the
instrument is broken and every other result from it is void.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from apps.reconciliation.worker import Finding, reconcile
from libs.clock import Clock


@dataclass(frozen=True)
class DetectionResult:
    detected: bool
    delay_seconds: float | None
    findings: list[Finding] = field(default_factory=list)

    def summary(self) -> str:
        """Never renders an undetected breach as a number.

        Averaged into a dashboard, "0 seconds to detect" would be the most
        flattering possible figure for the worst possible outcome. Unbounded is
        a different kind of value, not a large one, and it is reported as such.
        """
        if not self.detected:
            return "never detected"
        return f"detected after {self.delay_seconds}s"


def measure_detection(
    case_id: str, *, breach_at: datetime.datetime, clock: Clock
) -> DetectionResult:
    """Reconcile now, and express the outcome relative to when the breach landed.

    The reconciler is deterministic over quiescent state, so probing it
    repeatedly adds nothing: if it has nothing to say about the final state, it
    had nothing to say at every earlier moment too. That is why an undetected
    breach yields None rather than a large number -- the delay is not long, it
    is undefined.
    """
    report = reconcile(case_id)
    if not report.findings:
        return DetectionResult(detected=False, delay_seconds=None, findings=[])

    return DetectionResult(
        detected=True,
        delay_seconds=(clock.now() - breach_at).total_seconds(),
        findings=list(report.findings),
    )
