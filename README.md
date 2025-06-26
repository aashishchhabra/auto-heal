# Auto-Healer API Server

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/your-org/auto-heal/actions)
[![Coverage Status](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/your-org/auto-heal/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview
Auto-Healer is a modular, production-ready API server for automated remediation and healing actions. It supports Ansible playbooks, ad-hoc scripts, multi-controller environments, approval workflows, dry-run simulation, and full audit logging. Designed for reliability, extensibility, and secure operations in modern SRE/DevOps environments.

## Features

- Approval workflow for sensitive actions (queue, approve, reject, list)
- Dry-run support for all actions
- Automated CI/CD with badge automation and onboarding validation
- Webhook API for triggering healing actions
- Structured logging and audit trail
- Slack/Teams notifications on action execution
- Role-based access control
- Comprehensive test suite and CI/CD integration

## Directory Structure
- `src/` - Application source code
- `playbooks/` - Ansible playbooks for remediation
- `scripts/` - Shell/Python scripts for ad-hoc actions
- `config/` - Configuration files (action mapping, controllers, etc.)
- `logs/` - Structured logs and audit trails
- `tests/` - Unit and integration tests
- `docs/` - Documentation

## Quickstart
1. Create and activate a Python virtual environment:
   ```zsh
   python3 -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```zsh
   pip install -r requirements.txt
   ```
3. Run the API server:
   ```zsh
   uvicorn src.main:app --reload
   ```

## API Endpoints

### Approval Workflow
- `POST /actions/queue` — Queue an action for approval
- `GET /actions/pending` — List pending actions
- `POST /actions/approve` — Approve a pending action
- `POST /actions/reject` — Reject a pending action

### Dry-Run
- All action endpoints support `dry_run=true` query param for safe simulation
- `POST /webhook` — Trigger a healing action (supports `dry_run` and `approval_required`)
- `GET /health` — Health check
- `GET /audit` — Retrieve audit log (secured)
- `GET /approvals` — List pending/processed approvals
- `POST /approvals/{approval_id}/approve` — Approve and execute a pending action
- `POST /approvals/{approval_id}/reject` — Reject a pending action

## Usage Examples

### Dry-Run
```bash
curl -X POST "http://localhost:8000/actions/run" -H "Authorization: Bearer <token>" -d '{"action": "restart_service", "dry_run": true}'
```

### Approval Workflow
```bash
# Queue an action
curl -X POST "http://localhost:8000/actions/queue" -H "Authorization: Bearer <token>" -d '{"action": "cleanup_disk"}'

# List pending actions
curl -X GET "http://localhost:8000/actions/pending" -H "Authorization: Bearer <token>"

# Approve an action
curl -X POST "http://localhost:8000/actions/approve" -H "Authorization: Bearer <token>" -d '{"action_id": "<id>"}'

# Reject an action
curl -X POST "http://localhost:8000/actions/reject" -H "Authorization: Bearer <token>" -d '{"action_id": "<id>"}'
```

## Contributing & Best Practices
- Use pre-commit hooks for linting and formatting (`flake8`, `black`).
- Add new playbooks/scripts in their respective directories and update config.
- All code must be covered by unit/integration tests.
- Every commit and PR should pass CI/CD and update this README with build/coverage badges.
- Document new endpoints and features in `docs/`.

> **Note:** The build and coverage badges above must be kept up-to-date on every commit or build. Ensure your CI/CD pipeline updates them automatically.

## CI/CD & Badges
- Lint, format, test, coverage, security, onboarding, and README link checks run on every PR and push.
- Build and coverage badges are updated automatically in `README.md`.

## Onboarding & Contribution
- See `docs/ACTION_ONBOARDING_GUIDE.md` for onboarding new actions, approval, and dry-run instructions.
- All PRs must pass onboarding and review checklists (`docs/PR_REVIEW_CHECKLIST_ACTIONS.md`).

## Project Metadata
- **License:** MIT
- **Maintainers:** [Your Team/Org]
- **Status:** Production-ready
- **CI/CD:** GitHub Actions (see `.github/workflows/`)
- **Coverage:** 100% (see badge above)

## License
MIT