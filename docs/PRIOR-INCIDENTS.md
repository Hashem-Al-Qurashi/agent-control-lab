# Prior incidents

This lab demonstrates that an aggregate invariant can be breached while every
local control holds. A fair question is whether that shape occurs outside a lab.

Each entry below was **read at its primary source**, and each states what it does
and does **not** support. Entries that looked right and did not survive checking
are listed at the end rather than dropped, because which evidence was rejected is
part of the evidence.

> **Standing rule, inherited from the positioning work:** every public claim
> traces to a primary source, read directly — never a search summary. Four
> earlier claims in this project failed that test and are permanently retired.

---

## 1. ACIDRain — 22 verified attacks across ~2M eCommerce sites

**Source:** Todd Warszawski and Peter Bailis, *ACIDRain: Concurrency-Related
Attacks on Database-Backed Web Applications*, SIGMOD '17, Stanford InfoLab.
DOI [10.1145/3035918.3064037](https://dl.acm.org/doi/10.1145/3035918.3064037).
Peer-reviewed; PDF read directly.

The authors analysed 12 self-hosted eCommerce platforms *"written in four
languages and deployed on over 2M websites"* and identified and verified **22
critical attacks** that *"allow attackers to corrupt store inventory, over-spend
gift cards, and steal inventory."* They put the scope at *"over 50% of all
eCommerce websites."*

The concrete case is as plain as this lab's: in Magento, OpenCart and Oscar,
*"users can buy a single gift card, then spend it an unlimited number of times by
concurrently issuing checkout requests."*

**The clause that matters most is not the headline.** The paper reports that all
22 manifest under default isolation, *"and 17 vulnerabilities — due to incorrect
transaction usage — manifest even under the strongest transactional guarantees
offered by these databases."*

**Supports:** that individually-valid, authorized API requests routinely violate
application-level invariants in production software, at scale, and that raising
the isolation level does not fix it when the invariant sits outside the
transaction boundary. That is the same failure the reservation authority in `P0`
and `S1H` exists to prevent.

**Does not support:** this lab's specific structural claim. ACIDRain's
applications share one database, so a correctly scoped transaction is available
in principle — the defect is that the boundary was drawn wrongly. Here the
boundary **cannot** be drawn at all, because the inputs live in databases that no
transaction spans (ADR-009). ACIDRain is the same class of harm reached by an
easier road. Citing it as proof of the harder claim would be overreach.

## 2. Flexcoin — a concurrency race that ended a company

**Source:** quoted verbatim inside the ACIDRain paper (§1), attributed to
Flexcoin's own statement. Flexcoin's site is defunct, so the paper is the
readable primary record.

> "The attacker… successfully exploited a flaw in the code which allows transfers
> between Flexcoin users. By sending thousands of simultaneous requests, the
> attacker was able to 'move' coins from one user account to another until the
> sending account was overdrawn, before balances were updated."

The paper records that *"all Bitcoins in the Flexcoin exchange were stolen, all
users lost their stored Bitcoins, and the exchange was forced to shut down"* on
2 March 2014.

**Supports:** that this class is not theoretical and can be terminal. *"before
balances were updated"* is precisely the window `MODE-B.md` measures.

**Does not support:** anything about enterprise systems. It is a 2014 Bitcoin
exchange, and a reader entitled to say "not my world" would be right. Use it as a
mechanism illustration, never as the lead.

## 3. Twilio, July 2013 — the closest match to `S1`

**Source:** Twilio's own [billing incident post-mortem](https://www.twilio.com/blog/2013/07/billing-incident-post-mortem-breakdown-analysis-and-root-cause.html).

A Redis failure left account balances at zero and read-only. Per Twilio: *"With
all account balances at zero and read-only, Twilio usage that resulted in a
billing transaction… triggered the billing system to attempt a recharge using the
credit card associated with the customer's account."* Because charges could not
be recorded, further usage triggered further charges. **1.4% of customers** were
affected, some suspended when their cards were deactivated by repeated attempts.

The sentence that makes this the closest public analogue: each charge was a valid
response to the state the biller could see, and wrong against *the actual account
status maintained in the separate relational datastore*.

**Supports:** `S1` almost exactly. A decision-maker read a derived view that
disagreed with the authoritative store, every individual decision was correct
*given that view*, and the business outcome was wrong. Detection came through
customers and card deactivations — not through a failing component.

**Does not support:** a lag argument. Twilio's view was wrong through data loss,
not propagation delay. The structural point (deciding from a derived view that
disagrees with the authority) transfers; the mechanism does not.

## 4. US Dept. of Education NSLDS, April 2024 — aggregate limits breached at scale

**Source:** Federal Student Aid [electronic announcement, 25 April 2024](https://fsapartners.ed.gov/knowledge-center/library/electronic-announcements/2024-04-25/nslds-professional-access-aggregate-loan-total-calculation-issue-resolved-and-corrected-2023-24-isirs-sent-during-nslds-postscreening).

Aggregate loan totals were computed by incorrectly deducting duplicate
capitalised interest. When corrected, totals *"generally increased causing some
students to now exceed their aggregate loan limits."* About **36,786 borrowers**
were affected, and institutions had already disbursed on the incorrect figures.

**Supports:** that aggregate ceilings spanning many underlying records do get
breached in production, at scale, with real consequences, and that the breach is
invisible until something recomputes the aggregate — which is what the oracle
does here.

**Does not support:** the "no component failed" claim. This was a defect in the
aggregation itself. A component *was* wrong. It is adjacent evidence about
aggregate invariants, not an instance of this lab's mechanism, and stretching it
would be the kind of claim §6 of `GAP-ANALYSIS.md` exists to prevent.

---

## How to use these

Lead with **Twilio**: mainstream infrastructure, the company's own words, and the
closest analogue to `S1`. Follow with **ACIDRain** for scale and peer review.
Hold **Flexcoin** for when someone asks whether it is ever terminal. **NSLDS**
only if the conversation is specifically about aggregate ceilings.

**None of these is this lab's exact claim.** Each is closer to it than to
nothing, and the honest framing is:

> The harm is documented. The mechanisms differ. What is missing publicly is an
> instance where the invariant could not have been enforced by any single
> transaction because the data was never in one place — which is the case this
> lab constructs deterministically, because finding it in the wild requires
> access to systems that do not publish their postmortems.

## Rejected

- **"Klarna refund incident, Feb 2026"** and **"247 refunds, June 2026"** —
  uncorroborated aggregator blogs, no primary source. Permanently retired in
  `GAP-ANALYSIS.md` §6. Never use.
- **Knight Capital (2012)** — a deployment defect (a re-used feature flag
  activating dead code), not an aggregate-invariant breach. Frequently
  misappropriated for arguments like this one. Do not.
- **Generic "eventual consistency causes overselling" articles** — the top search
  results are teaching material with invented examples, not incidents. No
  reachable primary source.
