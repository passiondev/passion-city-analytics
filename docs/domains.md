# Passion City Analytics — Domain Definitions

test change 

## Domains

### 1. Sunday Ministry
- **Grain:** Two fact tables — see below
- **Primary fact tables:**
  - `fact_sunday_attendance` — one row = one service occurrence per location per schedule(aggregate headcount)
  - `fact_ministry_checkins` — one row = one person check-in per ministry area
- **Source:** Rock RMS Attendance module + manual aggregate entry
- **Ministry areas tracked via check-in:** Bloom, Passion Kids, Middle School,
  High School, Door Holders
- **Key questions:**
  - Why did attendance vary from the past 5 weeks?
  - How does Sunday trend across campuses (Trilith, Cumberland, 515)?
  - How many door holders were active this Sunday?

---

### 2. Giving
- **Grain:** Two fact tables - see below
- **Primary fact table:** `fact_giving` - one financial transaction (one gift)
- **Primary fact table:** `fact_scheduled_gift` - one recurring gift
- **Source:** Rock RMS FinancialTransaction + FinancialTransactionDetail // FinancialScheduledTransaction + FinancialScheduledTransactionDetail
- **Key questions:**
  - What are donations by week?
  - How many unique givers per week?
  - How does giving track vs prior year?
  - What is the giving journey by group status?

---

### 3. Engagement
- **Grain:** Multiple fact tables — see below
- **Primary fact tables:**
  - `fact_group_membership_history` — one row = one membership status period (SCD2)
  - `fact_group_enrollment` — one row = one join event (derived from history)
  - `fact_step_progress` — one row = one person at one step in one program
  - `fact_connection_requests` — one row = one connection request
  - `fact_JIL` — one row = one salvation decision
- **Source:** Rock RMS GroupMemberHistorical, GroupMember, Step, StepType,
  StepProgram, ConnectionRequest, Workflow
- **Key questions:**
  - How many people are currently in a group?
  - How many people dropped out this quarter?
  - What is our 90-day group retention rate?
  - How many door holders are active?
  - What is the Core completion rate by campus?
  - Where are people dropping off in the Core journey?
  - How many people requested baptism this month?
  - How many salvation decisions happened this quarter?
  - How long does it take to connect a volunteer request?

---

### 4. Events
- **Grain:** One row = one person check-in at one event occurrence
- **Primary fact table:** `fact_event_attendance`
- **Source:** Rock RMS Attendance (non-Sunday, event-type groups)
- **Event types include:** Core, Welcome to Church, Launch, Young Adults,
  and other midweek programming
- **Key questions:**
  - How many people attended Core last night?
  - Who came to Launch and are they new or returning?
  - What is event attendance trending over time?

---

### 5. Passion Camp
- **Grain:** One row = one line item order
- **Primary fact table:** `fact_orders`
- **Source:** MySQL database hosted on Digital Ocean
- **Supporting dimensions:**
  - `dim_event` — camp events
  - `dim_package` — package types
  - `dim_hotel` — hotel options and special accommodation flags
  - `dim_misc_item` — miscellaneous cost items
  - `dim_camp_user` — camp registrants, email-matched to dim_person where possible
- **Key questions:**
  - How much money are we owed per event?
  - Which hotels need special accommodations?
  - What is the cost breakdown by order type per event?
  - How many packages were ordered vs fulfilled?

---

## Shared Dimension

### dim_person
- **Grain:** One row = one unique person (canonical, deduped)
- **Source:** Rock RMS Person + PersonAlias
- **Attributes include:** campus, how they found us, attendance duration
  (from City Survey workflow), demographics
- **Role:** Spine of the entire model — every fact table joins through person_id
- **Note:** Must be built and tested before any fact table is built
- **Key challenge:** Rock RMS person merges and duplicates must be resolved
  here before any downstream modeling

---

## Cross-Domain Marts

### mart_engagement_giving
- **Grain:** One row = one person per month
- **Sources:** fact_giving + fact_group_membership_history joined through dim_person
- **Key question:** What is the giving journey by group status?

### mart_step_funnel
- **Grain:** One row = one person per program offering
- **Sources:** fact_step_progress pivoted wide
- **Key question:** What is the RSVP to attendance to completion funnel for Core?

### mart_sunday_summary
- **Grain:** One row = one Sunday per campus
- **Sources:** fact_sunday_attendance + fact_ministry_checkins joined on date and campus
- **Key question:** How did Sunday go across all ministry areas?

### mart_camp_engagement
- **Grain:** One row = one camp attendee per event
- **Sources:** dim_camp_user + dim_person (email match) + fact_group_membership_history
  + fact_giving
- **Key question:** Are Passion Camp attendees givers and group members?
  Is camp attendance correlated with deeper engagement?

---

## Data Notes

### Sunday Ministry — aggregate vs individual
`fact_sunday_attendance` contains manually entered headcounts with no
individual attendee data. `fact_ministry_checkins` contains person-level
records. These are separate fact tables joined on service date and campus
in reporting. Neither can be summed together — they measure different things.

### Door Holders
Appear in two domains intentionally:
- Sunday Ministry — were they there on Sunday?
- Engagement — are they active volunteers?
These reference the same person via dim_person and answer different questions.

### Engagement — group membership history
Rock RMS implements SCD2 on GroupMemberHistorical. Multiple rows per
GroupMemberId represent status changes over time. ExpireDateTime = 9999-01-01
indicates the current active row. Enables full retention analysis without
additional snapshot infrastructure.

### Engagement — Steps
Core has multiple offerings with varying numbers of classes (3 or 4).
fact_step_progress uses long format to accommodate variable step counts.
mart_step_funnel pivots by step order position, not step name, to keep
funnel analysis consistent across offerings.

### Engagement — connection requests
Connection requests span pastoral care (prayer, material help), ministry
placement (volunteer, family group, premarital counseling), and spiritual
milestones (baptism). All stored in fact_connection_requests tagged by
connection opportunity type.

### Engagement — salvation decisions
Sourced from the Jesus is Life workflow in Rock RMS. One row per decision.
A person may have multiple rows if Rock tracks recommitments separately.

### dim_person — City Survey
How long have you attended and how did you find us are stored as person
attributes derived from the City Survey workflow. These enrich dim_person
as descriptive columns rather than living in a separate fact table.

### Passion Camp — person matching
Camp users are matched to Rock RMS persons via email. This is a fuzzy join
resolved in an intermediate dbt model. Unmatched users remain in dim_camp_user
without a person_id. Match quality should be monitored as a dbt test.

### Passion Camp — pipeline architecture
Direct Power BI connection to MySQL on Digital Ocean is avoided due to
IP whitelisting complexity. Instead: MySQL → dbt → BigQuery → Power BI.
Power BI connects only to BigQuery, which has a stable Google endpoint.

### Distinguishing Sunday vs Event check-ins in Rock
TBD — need to confirm whether the split is by Group Type, day of week,
campus, or a combination. This determines filter logic in staging models.

---

## Modeling Notes
- Domains defined July 2026 based on recurring leadership questions
- Five domains: Sunday Ministry, Giving, Engagement, Events, Passion Camp
- Each domain gets its own Power BI semantic model
- Cross-domain questions are answered via marts, not by mixing semantic models
- dim_person is the spine of the entire model — built first, tested rigorously
- dbt staging layer splits Rock check-in data into Sunday vs Event streams
  before it reaches fact tables
- Passion Camp MySQL source requires separate dbt connection profile