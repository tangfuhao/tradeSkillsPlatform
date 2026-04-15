## ADDED Requirements

### Requirement: Users can upload a Markdown trading Skill as raw text
The platform SHALL allow a user to upload a Markdown Skill as plain text, optionally provide a title override, store the raw source, and validate that the Skill includes an identifiable title, execution cadence, AI reasoning section, and explicit risk-control guidance.

#### Scenario: Successful Skill upload
- **WHEN** a user uploads a Skill that includes the required runtime and risk sections
- **THEN** the platform stores the raw Skill source, creates a Skill record, and completes automated envelope extraction during the upload flow

#### Scenario: Missing AI reasoning or risk control is rejected
- **WHEN** the uploaded Skill does not contain an identifiable AI reasoning section or explicit risk-control rules
- **THEN** the platform rejects the upload and returns validation errors explaining what is missing

### Requirement: The platform extracts a Skill Envelope from the uploaded Skill
The platform SHALL extract and store a lightweight Skill Envelope from each valid Skill, including cadence, tool requirements, output schema, market context, execution/state contracts, and hard risk boundaries.

#### Scenario: Envelope extraction succeeds
- **WHEN** automated extraction can identify cadence and required tool signals from the Skill text
- **THEN** the platform stores the extracted Skill Envelope and makes the Skill available for execution

#### Scenario: One Skill supports both execution contexts
- **WHEN** a Skill passes automated validation and envelope extraction
- **THEN** the platform treats that Skill as one immutable execution contract that can be invoked in historical replay (`backtest`) or live triggering (`live_signal`) without a separate capability declaration on the Skill itself

#### Scenario: Envelope extraction fails safely
- **WHEN** the platform cannot reliably identify required runtime information from the Skill text
- **THEN** the upload is rejected and the Skill is not made executable

### Requirement: Validated Skills can be used for backtest execution immediately
The platform SHALL allow a validated Skill to be used for backtest creation without an additional review-state workflow.

#### Scenario: Valid Skill can backtest immediately
- **WHEN** a Skill passes automated validation and envelope extraction
- **THEN** the platform allows backtest creation as long as the requested window fits the local historical data coverage and cadence rules

### Requirement: Skills can be activated for live periodic signal generation
The platform SHALL allow a validated Skill to be activated as a live task using the cadence extracted from the Skill Envelope.

#### Scenario: Live task is created from a Skill
- **WHEN** a user activates live mode for a validated Skill
- **THEN** the platform creates a live task bound to that Skill and schedules periodic triggers according to the extracted cadence

### Requirement: Execution state is stored outside the Agent
The platform SHALL keep long-term execution state in platform storage and expose it to the Agent only through platform tools.

#### Scenario: Agent reads and writes state through tools
- **WHEN** an Agent run needs prior context or wants to persist a new focus symbol or last action
- **THEN** the Agent retrieves and writes that state through platform tools instead of relying on process-local memory
