# Auto-Healer API Server

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/aashishchhabra/auto-heal/actions)
[![Coverage Status](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/aashishchhabra/auto-heal/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview
Auto-Healer is a modular, production-ready API server for automated remediation and healing actions. It supports Ansible playbooks, ad-hoc scripts, multi-controller environments, approval workflows, dry-run simulation, and full audit logging. Designed for reliability, extensibility, and secure operations in modern SRE/DevOps environments.

## Why Auto-Healer?

Most teams end up in one of two places: an on-call rotation that hand-runs
the same handful of playbooks at 3am, or a heavyweight commercial AIOps
platform that remediates things you can't fully see or audit. Auto-Healer is
the middle path - a small, self-hosted service that turns an alert your team
already trusts (Grafana, Prometheus Alertmanager, or anything else that can
fire a webhook) into a controlled, logged action, without asking you to hand
your infrastructure credentials to a SaaS vendor.

What that means concretely:

- **It talks to what you actually run.** Bare-metal servers and VMs over SSH
  via Ansible, OpenShift/Kubernetes via `oc`/`kubectl` over SSH, or - with no
  bastion host and no SSH at all - directly against the Kubernetes API using
  a scoped, in-cluster ServiceAccount. Mix all three in the same deployment;
  most real infrastructure isn't one substrate.
- **Nothing runs unattended by default.** Every action supports `dry_run`
  before it's ever allowed to touch anything live. Cooldowns stop a real bug
  from becoming a restart loop. Rate limits absorb an alert storm instead of
  hammering the fleet. The riskiest actions - draining a node, scaling a
  production Deployment - can require a second, different person's approval,
  and a requester can never approve their own request.
- **Every action is provably accounted for.** The audit trail is hash-chained
  (tamper-EVIDENT: edit or delete a past entry and a verify check catches it)
  and can mirror, best-effort, to your existing SIEM - syslog or a plain
  HTTP/Elasticsearch sink, mapped to Elastic Common Schema so it's useful
  there without a bespoke index mapping. When someone asks "what ran against
  prod last night and who approved it," the answer isn't a Slack scrollback.
- **Access is scoped, not all-or-nothing.** Role-based permissions plus
  per-API-key restriction to a specific set of actions and controllers mean
  the credential your alerting system uses can be limited to exactly the
  handful of low-risk remediations it should ever trigger - nothing more.
- **Secrets stay out of plaintext config.** SSH keys, kubeconfigs, API
  tokens, and Vault's own credential can all be resolved from HashiCorp
  Vault at request time and, for anything written to disk, materialized to
  a private tempfile for the duration of one call and then deleted.
- **It's a config change, not a deployment.** Onboarding a new remediation
  means adding a playbook/script and a few lines of YAML - no redeploying
  the service, no vendor ticket. See `docs/on-call-case-study.html` for what
  that looks like end to end, from a Grafana alert to a resolved incident.
- **You can read every line of it.** No black-box remediation logic, no
  data leaving your network unless you configure shipping to say so. It's
  a FastAPI service you can run in a container, a pod, or a plain Python
  virtualenv, and audit yourself.

If your team already has an alerting pipeline and a growing pile of
"the same three fixes, every week" - this is built to sit exactly there.

## Features

- Approval workflow for sensitive actions (queue, approve, reject, list)
- Per-action cooldowns and per-caller/per-action rate limiting on `/webhook`
- Dry-run support for all actions
- Automated CI/CD with badge automation and onboarding validation
- Webhook API for triggering healing actions
- Structured, hash-chained (tamper-evident) audit trail with optional rotation/retention, and optional shipping to syslog/Elasticsearch/any HTTP log platform
- Slack/Teams notifications on action execution
- Role-based access control, plus optional per-API-key scoping to a specific set of actions/controllers
- Optional HashiCorp Vault-backed secrets (API keys, controller SSH/kube credentials), with static-token or in-cluster Kubernetes Vault auth
- Direct Kubernetes/OpenShift API actions (`kube_action`) alongside SSH-based execution
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
- `GET /audit/verify` — Check the audit log's hash chain for tampering (secured)
- `GET /approvals` — List pending/processed approvals
- `POST /approvals/{approval_id}/approve` — Approve and execute a pending action
- `POST /approvals/{approval_id}/reject` — Reject a pending action

Approving/rejecting requires the `approve_actions` permission (see
`config/auth.yaml`; `readonly` does not have it by default), and a
requester can never approve or reject their own pending request, even
with a role that otherwise has `approve_actions`. Triggering `/webhook`
at all requires `execute_actions` (`readonly` doesn't have this either);
individual API keys can additionally be scoped to a narrower set of
actions/controllers than their role otherwise permits - see "Fine-Grained
API Key Scoping" in `docs/ACTION_ONBOARDING_GUIDE.md`.

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

## How to Specify Actions, Target Nodes, and Controllers

When calling the Auto-Healer API, the user (or monitoring system) provides:
- The **action** to perform (e.g., `restart_service`)
- **Parameters** for the action (e.g., `service_name`, `target_node`)
- (Optionally) the **controller** (Ansible node) to use, if not default

**Example API Payload:**
```json
{
  "action": "restart_service",
  "parameters": {
    "service_name": "nginx",
    "target_node": "vm1.example.com"
  },
  "controller": "dc1-ansible"  // Optional: override default controller
}
```

**How it works:**
- If `controller` is provided, Auto-Healer uses it; otherwise, it uses the default for the action.
- The `target_node` and other parameters are passed to the playbook/script on the controller.
- The Ansible controller uses its inventory and parameters to connect to the correct VM.

**Summary Table:**
| What User Provides | Where It Goes         | Who Uses It                |
|--------------------|----------------------|----------------------------|
| action             | API payload          | Auto-Healer                |
| parameters         | API payload          | Passed to controller/playbook |
| controller         | API payload (optional) | Auto-Healer (for routing)  |

## How Remote Actions Are Executed

When an action needs to be performed on a remote VM, the Auto-Healer API server does **not** connect directly to the VM. Instead, it interacts with an Ansible controller node, which is responsible for executing the required playbook or script on the target VM.

- **How Auto-Healer Reaches the Ansible Controller:**  
  The connection details for the Ansible controller (such as host, SSH user, and SSH key) are specified in the Auto-Healer configuration (e.g., `config/actions.yaml`). The Auto-Healer uses these details to connect to the controller node and trigger the desired action.

- **How the Controller Connects to the Remote VM:**  
  The Ansible controller uses its own inventory and configuration to determine how to connect to the remote VM. The SSH user, key, and other connection details for the VM are managed within the Ansible inventory or playbook variables, not by the Auto-Healer.

**Example:**
```yaml
controllers:
  dc1-ansible:
    host: ansible-controller.example.com
    ssh_user: ansible
    ssh_key: /path/to/key
actions:
  restart_service:
    controller: dc1-ansible
    ...
```
And in your Ansible inventory:
```
[webservers]
vm1.example.com ansible_user=ubuntu ansible_ssh_private_key_file=/keys/ubuntu.pem
```

**Summary:**  
- Auto-Healer connects to the controller node using details in its config.
- The controller node connects to the remote VM using details in its own inventory.
- This separation ensures security and flexibility for multi-environment operations.

## Kubernetes & Helm Deployment

Auto-Healer can be deployed to Kubernetes or OpenShift using the provided manifests or Helm chart.

### Kubernetes Manifests
- See `k8s/` directory for:
  - `deployment.yaml`: Main Deployment
  - `service.yaml`: ClusterIP Service
  - `configmap.yaml`: Mounts config files
  - `secret.yaml`: Stores API key (base64-encoded)
- Apply all at once:
  ```sh
  kubectl apply -f k8s/
  ```
- Health, liveness, and readiness endpoints:
  - `/health` — General health check
  - `/live` — Liveness probe
  - `/ready` — Readiness probe

### Helm Chart
- See `helm/` directory for a production-ready Helm chart.
- Install with:
  ```sh
  helm install auto-healer ./helm --set env.API_KEY=<your-api-key>
  ```
- Upgrade, rollback, and config instructions in `helm/templates/NOTES.txt`.

### Scaling & Rolling Updates
- Scale with `kubectl scale deployment/auto-healer --replicas=3` or edit `replicaCount` in Helm `values.yaml`.
- Rolling updates are supported by default. Update image/tag and re-apply.

### Service Discovery
- Access via `auto-healer` service in-cluster, or expose via Ingress/LoadBalancer as needed.

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
- `docs/on-call-case-study.html` walks through an illustrative on-call night — Grafana/Alertmanager wired to Auto-Healer across bare metal, VMs, and an OpenShift cluster — as a concrete picture of how the pieces above fit together. Open it in a browser (GitHub renders it as source, not as a page).

## Project Metadata
- **License:** MIT
- **Maintainers:** Aashish Chhabra
- **Status:** Production-ready
- **CI/CD:** GitHub Actions (see `.github/workflows/`)
- **Coverage:** 100% (see badge above)
- **Security Scan:** Bandit (No issues identified., last scan: 2025-06-26)

## Contributors

Thanks goes to these wonderful people (emoji key):

<!-- ALL-CONTRIBUTORS-LIST:START -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

This project follows the [all-contributors](https://allcontributors.org) specification. Contributions of any kind welcome!

## License
MIT