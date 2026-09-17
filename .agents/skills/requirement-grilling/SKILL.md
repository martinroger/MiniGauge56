---
name: requirement-grilling
description: Guides the agent to perform interactive requirement grilling during the planning phase for complex features, architectural setups, and formalize agent scope, constraints, and traceability tracking in Markdown.
---

# Requirement Grilling & Interactive Planning Skill

When this skill is activated or when starting a complex architectural task:

1. **Pause Implementation**: Do not begin writing code or editing files immediately.
2. **Formulate 3-5 Specific Questions**:
   - Technical constraints (framework versions, hardware targets, OS compatibility).
   - Architectural preferences (design patterns, file structure, state management).
   - Operational scope boundaries, edge cases, and external dependencies.
3. **Wait for Clarification**: Incorporate the user's responses into the final plan.
4. **Generate / Update Markdown Tracking Files**:
   - **`REQUIREMENTS.md`**: Formalize system requirements, operational boundaries, and an **Implementation Traceability Matrix** mapping requirements directly to specific source code/config files and verification methods.
   - **`CONSTRAINTS.md`**: Document platform & tooling constraints, hardware safety rules, and software architecture constraints.
   - **Root `README.md` / `PROJECT_SUMMARY.md`**: Ensure repository-level summaries accurately describe agent scope boundaries, technical stack, and repo structure.
