## ADDED Requirements

### Requirement: Users can upload a Markdown trading Skill as raw text
The platform SHALL allow an authenticated user to upload a Markdown Skill as plain text, store the raw source immutably, and validate that the Skill includes a title, execution cadence, an AI reasoning section, and explicit risk-control guidance.

#### Scenario: Successful Skill upload
- **WHEN** a user uploads a Skill that includes the required runtime and risk sections
- **THEN** the platform stores the raw Skill source, creates a new Skill version, and starts automated validation and envelope extraction

#### Scenario: Missing AI reasoning or risk control is rejected
- **WHEN** the uploaded Skill does not contain an identifiable AI reasoning section or explicit risk-control rules
- **THEN** the platform rejects the upload and returns validation errors explaining what is missing

### Requirement: The platform extracts a Skill Envelope from the uploaded Skill
The platform SHALL extract and store a lightweight Skill Envelope from each valid Skill, including runtime modes, cadence, tool requirements, output schema, market context, and hard risk boundaries.

#### Scenario: Envelope extraction succeeds
- **WHEN** automated extraction can identify cadence, mode, and required tool signals from the Skill text
- **THEN** the platform stores the extracted Skill Envelope and makes the Skill selectable for preview backtests

#### Scenario: Envelope extraction fails safely
- **WHEN** the platform cannot reliably identify required runtime information from the Skill text
- **THEN** the platform marks the Skill version as invalid and prevents it from running until the Skill is revised

### Requirement: Skill versions use preview-first execution eligibility
The platform SHALL allow an automatically validated Skill version to run immediate preview backtests in the recent limited window and SHALL require manual approval before the version can run larger historical windows.

#### Scenario: Preview-eligible Skill can backtest immediately
- **WHEN** a Skill version passes automated validation
- **THEN** the platform marks it as preview-eligible and allows recent-window backtest creation without manual review

#### Scenario: Full-history request requires review
- **WHEN** a user requests a larger historical window than the preview scope allows
- **THEN** the platform blocks the run request until a reviewer approves the Skill version for larger history access

### Requirement: Skills can be activated for live periodic signal generation
The platform SHALL allow a validated Skill version to be activated as a live task using the cadence extracted from the Skill Envelope.

#### Scenario: Live task is created from a Skill
- **WHEN** a user activates live mode for a preview-eligible or approved Skill version
- **THEN** the platform creates a live task bound to that Skill version and schedules periodic triggers according to the extracted cadence

### Requirement: Strategy state is stored outside the Agent
The platform SHALL keep long-term strategy state in platform storage and expose it to the Agent only through platform tools.

#### Scenario: Agent reads and writes state through tools
- **WHEN** an Agent run needs prior context or wants to persist a new focus symbol or last action
- **THEN** the Agent retrieves and writes that state through platform tools instead of relying on process-local memory
