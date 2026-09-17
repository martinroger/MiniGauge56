---
name: workspace-rules-integrator
description: Use this skill on-demand when the user wants to evaluate the current workspace or subproject context against the central repository in ~/Documents/antigravity-rules, and interactively select, adapt, and install relevant rules and skills into the local workspace folder with explicit confirmation.
---

# Workspace Rules & Skills Integrator

Use this skill when invoked by the user in any project or subproject workspace to analyze the current codebase context, compare it with the centralized catalog in `~/Documents/antigravity-rules`, and interactively install or update matching local rules and skills.

---

## Operating Workflow

### Phase 1: Local Context Inspection
Inspect the current workspace directory (or active subfolder if focused on a subproject):
1. **Identify Technology & Frameworks**:
   - Check build files: `CMakeLists.txt`, `package.json`, `Cargo.toml`, `pyproject.toml`, `Makefile`, etc.
   - Detect hardware targets (e.g. ESP32, ESP32-S3, STM32), ESP-IDF version (`idf.py --version` or `sdkconfig`), Arduino, etc.
   - Check documentation files: `README.md`, `REQUIREMENTS.md`, `CONSTRAINTS.md`, `TOO.MD`, `SCENARIOS.md`, etc.
2. **Inspect Existing Local Customizations**:
   - Check for existing `GEMINI.md`, `AGENTS.md`, or `.agents/rules/` files.
   - Check `.agents/skills/` or `.gemini/skills/` for currently installed local skills.

---

### Phase 2: Central Repository Review
Read and review the centralized repository at `~/Documents/antigravity-rules`:
1. **Examine Rules Catalog (`rules/`)**:
   - [`rules/base.geminirules`](rules/base.geminirules): Core execution quality, planning, debugging, nomenclature standards.
   - [`rules/documentation.geminirules`](rules/documentation.geminirules): Markdown tracking, rendered artifacts, relative links, sequence diagrams, `/docs/` hygiene.
   - [`rules/esp-idf.geminirules`](rules/esp-idf.geminirules): ESP32 hardware target, virtual environments, read-only component boundaries, FreeRTOS pinning, strapping pins.
   - Any other newly added domain-specific `.geminirules`.
2. **Examine Skills Catalog (`skills/`)**:
   - Inspect all available skills in `~/Documents/antigravity-rules/skills/` and review their `SKILL.md` descriptions to find applicable workflows.

---

### Phase 3: Matchmaking & Interactive Recommendation
Formulate a tailored proposal matching the detected project type:
- **Baseline Rules**: Recommend universal rules (`base.geminirules`, `documentation.geminirules`).
- **Domain/Platform Rules**: Recommend specialized rules matching the detected stack (e.g. `esp-idf.geminirules` for ESP32 projects).
- **Relevant Skills**: Recommend specific skills that enhance development in this workspace (e.g. `requirement-grilling`, `esp-development`, `esp32-web-telemetry-portal`, `rule-harvesting`, etc.).

---

### Phase 4: Interactive User Confirmation
> [!IMPORTANT]
> **Human-in-the-Loop Requirement**: Never create or modify local rule/skill files without presenting the recommendations to the user and asking for explicit confirmation.

1. Present an interactive summary or questionnaire to the user:
   - Explain which rules and skills match the workspace and **why** they are relevant.
   - Show where the files will be placed (e.g. `GEMINI.md` at project root vs subfolder, `.agents/skills/<name>/`).
   - Allow the user to accept all, pick specific items, or request custom adjustments.

---

### Phase 5: Execution & Installation (Post-Confirmation)
Upon explicit user approval:
1. **Install / Update Rules**:
   - Write or merge approved rules into the target folder's `GEMINI.md` (or `AGENTS.md` / `.agents/rules/`).
   - Ensure rules are tailored to any local subproject boundaries if operating in a mono-repo.
2. **Install / Copy Skills**:
   - Create local skill folders under `.agents/skills/<skill-name>/` in the target workspace.
   - Copy or adapt the corresponding `SKILL.md`, `scripts/`, and `references/` from `~/Documents/antigravity-rules/skills/<skill-name>/`.
3. **Summarize**:
   - List all newly created or updated files with clickable file links.
   - Provide quick instructions on how the user can test the newly imported rules and skills.
