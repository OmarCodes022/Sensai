# Phase 1 product acceptance: one creator, four reviewable outputs (T02)

These are **product acceptance definitions**, not an implemented four-output
flow. The current chat runtime does not ingest DMs or analytics, save these
artifacts, export them, schedule content, or publish. This scope does not
require keynote planning.

## Creator and recurring problem

**Nadia**, a fictional solo creator who owns the fictional skincare brand
**Serein Studio**, makes simple hydration content for adults on Instagram.
Each Monday she must turn approved product facts, the prior week's aggregate
Instagram performance, and questions received in her brand inbox into a
week's content plan. Doing this by hand repeatedly risks invented performance
figures, unsupported skincare claims, and accidentally exposing private DM
details. The goal is to prepare material for Nadia to review, not to speak to
customers or publish on her behalf.

One weekly run covers the previous Monday 00:00 through Sunday 23:59 in the
brand's declared time zone; proposed calendar dates are in the following
week. Each output must be a **separately saved, privately reviewable artifact**
with a run/week identifier, generation date and validation status. Reviewable
means Nadia can see the actual text, provenance and intended channel before
choosing what to do with it; a transient chat answer is not an output.

| Saved output | Measurable success | Failure / never silently substitute |
| --- | --- | --- |
| Creator-voice post drafts | At least **3 distinct Instagram post drafts** for the coming week, each with a draft ID, caption in Nadia's approved brand voice, intended channel and a reference from every product-specific factual statement to an exact, currently approved claim and its evidence. They remain editable drafts. | Missing or expired approvals, unsupported results/medical promises, generic text passed off as Nadia's approved voice, fewer than 3 valid drafts, or publishing any draft. Do not make up a safe-sounding product benefit to fill the quota. |
| Anonymized DM reply suggestions | **One unsent suggestion per eligible, privacy-sanitized question**, up to 5 for review, with an ephemeral case key and generic context only. Record the number of eligible questions; a verified zero is a valid saved empty queue with count 0, not fabricated questions. Product statements use the same approved-claim register as posts. | Including names, handles, contact details, raw message IDs/quotes or health details in the saved artifact; replying/sending without approval; claiming answers to unverified product questions; or treating an unavailable inbox as zero. |
| Dated, sourced weekly report | **One report** names its 7-day interval, time zone, extraction timestamp, aggregate source for each figure, `accounts_reached`, `accounts_engaged`, and `engagement_rate = accounts_engaged / accounts_reached × 100` where the source defines both counts for the same cohort. State `n/a (zero reach)` instead of dividing by zero. Include the actual figures and a short interpretation clearly distinguished from the figures. | Invented, untraceable, stale, negative or mismatched-period figures; `accounts_engaged > accounts_reached`; misleading percentages or zero substituted for missing data; personal-level analytics exported. A missing required source fails the report rather than producing a plausible estimate. |
| Proposed dated/channel content calendar | **At least 3 proposed entries** on distinct dates in the following week, each with local date, `Instagram` channel, referenced post draft ID and proposed theme/time. Entries are a saved proposal, **not remotely scheduled or published**. | Dates outside the proposed week, nonexistent draft references, absent channel, pretending entries have been scheduled, or any automatic publication. |

All four are successful only when their own checks pass and all four valid
artifacts are saved for review. Report a failed or incomplete run honestly
without labeling it a successful four-output run. Zero eligible DMs is
different from no access to the DM source.

## Inputs, export and release boundary

Inputs needed are an approved brand-voice brief, a versioned register of
exact product claims with supporting evidence and validity dates, an
authorized inbox sample with a local privacy-sanitization path, the declared
time zone and complete aggregate analytics for the report window, and
calendar constraints for the coming week. Missing, stale, conflicting or
invalid inputs fail the affected output; do not fill gaps with generated
facts, identities or metrics. Only de-identified DM context may reach
generation or the saved suggestion. See [privacy-and-claims.md](privacy-and-claims.md)
for the proposed input/output policy and refusal behavior.

After validation, **private/local export happens automatically** to a
creator-controlled non-public location; no approval click is needed just to
retain validated private artifacts. Validation failure means no export of an
unsafe artifact. A public link, publication, external report delivery or
sending a DM requires Nadia's **explicit approval of the exact content and
each exact destination** after review; changing either invalidates that
approval. A scheduled run may prepare drafts and proposals only. It never
sends, remotely schedules, auto-publishes or makes a public link.
