# AI Purchasing Agent — Project Rules

## Isolation
- This repository is completely independent.
- Never access, modify, execute, import, or copy from the Stock Agent project.
- All assignment code, data, tests, configuration, and documentation must stay in this repository.

## Assignment
Build a full-stack AI Purchasing Agent that:
1. Investigates relevant purchasing information.
2. Makes a purchasing decision.
3. Takes an appropriate action.
4. Validates the outcome.
5. Handles failures and escalation.

## Engineering
- Prefer simple, reliable architecture.
- Do not over-engineer.
- Business constraints must be enforced deterministically.
- The LLM must not bypass validation or authorization.
- Every agent action should be traceable.
- Mock APIs and datasets are acceptable.
- Keep the implementation easy to explain in an interview.

## Verification
- Run tests after meaningful changes.
- Do not claim something works without verifying it.
- Never commit API keys, tokens, passwords, or other secrets.
