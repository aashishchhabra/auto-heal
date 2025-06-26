# Phases for Auto-Healer API Server Implementation

---

## **Phase 1: Project Foundation & Core API**

### **1.1 Project Setup**
- **Story:** Initialize project structure and tooling
  - Task: Set up repository and directory structure (`src/`, `playbooks/`, `scripts/`, `config/`, `logs/`, `tests/`, `docs/`) **[COMPLETE]**
    - Subtask: Create root project directory **[COMPLETE]**
    - Subtask: Create all required subdirectories **[COMPLETE]**
    - Subtask: Add placeholder files (e.g., `.gitkeep`) to empty dirs **[COMPLETE]**
  - Task: Initialize Python/Node.js/Go project (choose stack) **[COMPLETE]**
    - Subtask: Select language and framework **[COMPLETE]**
    - Subtask: Initialize project with package manager (e.g., `pip`, `npm`, `go mod`) **[COMPLETE]**
    - Subtask: Add main entrypoint file **[COMPLETE]**
  - Task: Set up linting, formatting, and pre-commit hooks **[COMPLETE]**
    - Subtask: Choose linter and formatter (e.g., flake8, black, eslint, prettier) **[COMPLETE]**
    - Subtask: Add config files for linting/formatting **[COMPLETE]**
    - Subtask: Set up pre-commit hooks (e.g., with `pre-commit` or Husky) **[COMPLETE]**
  - Task: Add initial `README.md` and documentation **[COMPLETE]**
    - Subtask: Write project overview **[COMPLETE]**
    - Subtask: Document directory structure **[COMPLETE]**
    - Subtask: Add setup and usage instructions **[COMPLETE]**

### **1.2 Core API Server**
- **Story:** Implement basic API server with health check
  - Task: Create `/health` endpoint **[COMPLETE]**
    - Subtask: Define route and handler **[COMPLETE]**
    - Subtask: Return status and version info **[COMPLETE]**
    - Subtask: Add test for health endpoint **[COMPLETE]**
  - Task: Set up basic server framework (Flask/FastAPI/Express/etc.) **[COMPLETE]**
    - Subtask: Install framework dependencies **[COMPLETE]**
    - Subtask: Implement server startup logic **[COMPLETE]**
    - Subtask: Add config for host/port/env **[COMPLETE]**
  - Task: Add structured logging **[COMPLETE]**
    - Subtask: Choose logging library **[COMPLETE]**
    - Subtask: Configure log format (JSON, timestamps, etc.) **[COMPLETE]**
    - Subtask: Add log statements to server startup and health endpoint **[COMPLETE]**

---

## **Phase 2: Authentication & Security**

### **2.1 API Authentication**
- **Story:** Secure API endpoints
  - Task: Implement API key/token authentication **[COMPLETE]**
    - Subtask: Define API key/token storage (env/config) **[COMPLETE]**
    - Subtask: Add middleware to check auth header **[COMPLETE]**
    - Subtask: Return 401 on missing/invalid key **[COMPLETE]**
    - Subtask: Add tests for auth logic **[COMPLETE]**
  - Task: Add middleware for authentication **[COMPLETE]**
    - Subtask: Integrate middleware with all protected endpoints **[COMPLETE]**
    - Subtask: Ensure health endpoint is public (if desired) **[COMPLETE]**
  - Task: Document authentication method **[COMPLETE]**
    - Subtask: Add API key/token usage to README **[COMPLETE]**
    - Subtask: Document how to generate/rotate keys **[COMPLETE]**

### **2.2 Authorization**
- **Story:** Add controller override authorization
  - Task: Define roles/permissions in config **[COMPLETE]**
    - Subtask: Design roles/permissions structure in config **[COMPLETE]**
    - Subtask: Add example roles (admin, operator, readonly) **[COMPLETE]**
  - Task: Enforce permissions for controller overrides **[COMPLETE]**
    - Subtask: Implement permission checks in override logic **[COMPLETE]**
    - Subtask: Return 403 on unauthorized override **[COMPLETE]**
    - Subtask: Add tests for permission enforcement **[COMPLETE]**

---

## **Phase 3: Action Mapping & Execution Engine**

### **3.1 Action Mapping**
- **Story:** Map events to actions and controllers
  - Task: Design `actions.yaml` config structure **[COMPLETE]**
    - Subtask: Define schema for mapping events to actions/controllers **[COMPLETE]**
    - Subtask: Add support for parameters and defaults **[COMPLETE]**
    - Subtask: Provide example config **[COMPLETE]**
  - Task: Implement config loader and validator **[COMPLETE]**
    - Subtask: Write loader to parse YAML/JSON **[COMPLETE]**
    - Subtask: Validate config against schema **[COMPLETE]**
    - Subtask: Handle config reloads (optional)
  - Task: Support parameterization in mappings **[COMPLETE]**
    - Subtask: Allow event payload to override parameters **[COMPLETE]**
    - Subtask: Document parameterization in config **[COMPLETE]**

### **3.2 Controller Inventory**
- **Story:** Manage controller/client nodes
  - Task: Design `controllers.yaml` structure **[COMPLETE]**
    - Subtask: Define schema for controller/client metadata **[COMPLETE]**
    - Subtask: Add example entries for Ansible, oc, etc. **[COMPLETE]**
  - Task: Implement controller inventory loader **[COMPLETE]**
    - Subtask: Write loader to parse controllers config **[COMPLETE]**
    - Subtask: Validate controller types and required fields **[COMPLETE]**
  - Task: Validate controller existence and type **[COMPLETE]**
    - Subtask: Check controller exists before execution **[COMPLETE]**
    - Subtask: Return error if controller is missing/invalid **[COMPLETE]**

### **3.3 Action Executor**
- **Story:** Execute playbooks/scripts on controllers
  - Task: Implement SSH/API execution logic **[COMPLETE]**
    - Subtask: Implement SSH connection logic **[COMPLETE]**
    - Subtask: Implement API call logic (if needed)
    - Subtask: Handle connection errors and timeouts **[COMPLETE]**
  - Task: Support Ansible playbooks and ad-hoc scripts **[COMPLETE]**
    - Subtask: Add logic to run Ansible playbooks via CLI **[COMPLETE]**
    - Subtask: Add logic to run shell/Python scripts **[COMPLETE]**
    - Subtask: Support passing parameters to playbooks/scripts **[COMPLETE]**
  - Task: Capture and return execution output and errors **[COMPLETE]**
    - Subtask: Capture stdout/stderr from executions **[COMPLETE]**
    - Subtask: Parse and format results for API response **[COMPLETE]**
    - Subtask: Log execution details **[COMPLETE]**

---

## **Phase 4: Webhook Handling & Dynamic Routing**

### **4.1 Webhook Endpoint**
- **Story:** Handle incoming webhooks **[COMPLETE]**
  - Task: Implement `/webhook` endpoint **[COMPLETE]**
    - Subtask: Define route and handler **[COMPLETE]**
    - Subtask: Accept and parse JSON payloads **[COMPLETE]**
    - Subtask: Return 200/400/500 as appropriate **[COMPLETE]**
  - Task: Parse and validate payloads **[COMPLETE]**
    - Subtask: Define payload schema **[COMPLETE]**
    - Subtask: Validate required fields (event_type, target, etc.) **[COMPLETE]**
    - Subtask: Return error on invalid payload **[COMPLETE]**
  - Task: Extract event type, target, and controller override **[COMPLETE]**
    - Subtask: Parse fields from payload **[COMPLETE]**
    - Subtask: Pass extracted info to action mapping logic **[COMPLETE]**

### **4.2 Dynamic Controller Selection**
- **Story:** Support controller override from webhook **[COMPLETE]**
  - Task: Check for `controller_override` in payload **[COMPLETE]**
    - Subtask: Parse override field if present **[COMPLETE]**
    - Subtask: Validate override value **[COMPLETE]**
  - Task: Validate and authorize override **[COMPLETE]**
    - Subtask: Check permissions for override **[COMPLETE]**
    - Subtask: Return error if not allowed **[COMPLETE]**
  - Task: Fallback to default controller if not specified **[COMPLETE]**
    - Subtask: Use mapping config if no override **[COMPLETE]**
    - Subtask: Log which controller was selected **[COMPLETE]**

---

## **Phase 5: Logging, Auditing, and Error Handling**

### **5.1 Structured Logging**
- **Story:** Implement structured and contextual logging
  - Task: Log all requests, actions, controllers, and results
    - Subtask: Add request logging middleware **[COMPLETE]**
    - Subtask: Log action execution details **[COMPLETE]**
    - Subtask: Log controller selection and overrides **[COMPLETE]**
  - Task: Store logs in `logs/` directory
    - Subtask: Configure log file rotation/retention **[COMPLETE]**
    - Subtask: Ensure logs are structured (JSON, etc.) **[COMPLETE]**

### **5.2 Audit Trail**
- **Story:** Maintain execution audit trail
  - Task: Record action details, user, controller, and outcome
    - Subtask: Define audit log schema **[COMPLETE]**
    - Subtask: Write audit entries on every action **[COMPLETE]**
  - Task: Implement `/audit` endpoint (secured) for audit retrieval
    - Subtask: Define route and handler **[COMPLETE]**
    - Subtask: Secure endpoint with authentication/authorization **[COMPLETE]**
    - Subtask: Support filtering by date, action, user **[COMPLETE]**

### **5.3 Error Handling**
- **Story:** Robust error handling and reporting
  - Task: Standardize error responses
    - Subtask: Define error response schema **[COMPLETE]**
    - Subtask: Return consistent error codes/messages **[COMPLETE]**
  - Task: Log errors and failed attempts
    - Subtask: Log all exceptions and failures **[COMPLETE]**
    - Subtask: Include context in error logs **[COMPLETE]**

---

## **Phase 6: Sample Actions & Extensibility**

### **6.1 Sample Playbooks/Scripts**
- **Story:** Provide sample healing actions
  - Task: Add playbook to restart a service
    - Subtask: Write Ansible playbook for service restart **[COMPLETE]**
    - Subtask: Add example mapping in config **[COMPLETE]**
    - Subtask: Test playbook execution **[COMPLETE]**
  - Task: Add script to clean up disk space
    - Subtask: Write shell/Python script for disk cleanup **[COMPLETE]**
    - Subtask: Add example mapping in config **[COMPLETE]**
    - Subtask: Test script execution **[COMPLETE]**
  - Task: Add health check script/playbook
    - Subtask: Write health check script/playbook **[COMPLETE]**
    - Subtask: Add example mapping in config **[COMPLETE]**
    - Subtask: Test health check execution **[COMPLETE]**

### **6.2 Onboarding New Actions**
- **Story:** Enable modular onboarding via GitOps/CI **[COMPLETE]**
  - Task: Document process for adding new playbooks/scripts **[COMPLETE]**
    - Subtask: Write onboarding guide in `docs/` **[COMPLETE]**
    - Subtask: Add PR review checklist for new actions **[COMPLETE]**
  - Task: Auto-discover new actions from `playbooks/` and `scripts/` **[COMPLETE]**
    - Subtask: Implement directory scan logic **[COMPLETE]**
    - Subtask: Update config loader to support auto-discovery **[COMPLETE]**

---

## **Phase 7: Notifications & Advanced Features**

### **7.1 Notification Hooks**
- **Story:** Integrate with Slack/Teams for notifications **[COMPLETE]**
  - Task: Add notification config **[COMPLETE]**
    - Subtask: Define notification settings in config **[COMPLETE]**
    - Subtask: Add example for Slack/Teams **[COMPLETE]**
  - Task: Implement notification sending on action execution/failure **[COMPLETE]**
    - Subtask: Integrate with Slack/Teams API **[COMPLETE]**
    - Subtask: Send notifications on success/failure **[COMPLETE]**
    - Subtask: Add tests for notification logic **[COMPLETE]**

### **7.2 Approval & Dry-Run**
- **Story:** Add approval and dry-run capabilities
  - Task: Implement approval workflow (manual or chatops) **[COMPLETE]**
    - Subtask: Define approval process and states **[COMPLETE]**
    - Subtask: Integrate with chatops or web UI for approvals **[COMPLETE]**
    - Subtask: Block execution until approved **[COMPLETE]**
  - Task: Add dry-run mode for actions **[COMPLETE]**
    - Subtask: Implement dry-run logic in executor **[COMPLETE]**
    - Subtask: Allow dry-run via API or config **[COMPLETE]**
    - Subtask: Return simulated results **[COMPLETE]**

---

## **Phase 8: Testing, CI/CD, and Documentation**

### **8.1 Testing**
- **Story:** Ensure code quality and reliability
  - Task: Write unit and integration tests **[COMPLETE]**
    - Subtask: Write unit tests for all modules **[COMPLETE]**
    - Subtask: Write integration tests for API endpoints **[COMPLETE]**
    - Subtask: Add tests for error and edge cases **[COMPLETE]**
    - Subtask: Add integration and unit tests for approval workflow **[COMPLETE]**
    - Subtask: Add integration tests for dry-run mode **[COMPLETE]**
  - Task: Add test cases for all endpoints and scenarios **[COMPLETE]**
    - Subtask: Define test scenarios for each endpoint **[COMPLETE]**
    - Subtask: Automate test execution in CI **[COMPLETE]**

### **8.2 CI/CD Integration**
- **Story:** Automate build, test, and deployment **[COMPLETE]**
  - Task: Set up CI/CD pipeline **[COMPLETE]**
    - Subtask: Choose CI/CD tool (GitHub Actions, GitLab CI, etc.) **[COMPLETE]**
    - Subtask: Configure build, test, and deploy stages **[COMPLETE]**
    - Subtask: Add status badges to README **[COMPLETE]**
  - Task: Automate onboarding of new actions via PRs **[COMPLETE]**
    - Subtask: Add CI checks for new playbooks/scripts **[COMPLETE]**
    - Subtask: Validate config and action files in PRs **[COMPLETE]**

### **8.3 Documentation**
- **Story:** Comprehensive user and developer docs **[COMPLETE]**
  - Task: Document API endpoints, config, and onboarding **[COMPLETE]**
    - Subtask: Write API reference docs **[COMPLETE]**
    - Subtask: Document config file formats and examples **[COMPLETE]**
    - Subtask: Add onboarding guide for new users **[COMPLETE]**
  - Task: Provide usage examples and troubleshooting guide **[COMPLETE]**
    - Subtask: Add example webhook payloads **[COMPLETE]**
    - Subtask: Document common issues and solutions **[COMPLETE]**

---

# **Future Phases & Roadmap**

## Phase 9: Containerization & Orchestration
**Goal:** Run Auto-Healer as a single Docker container, Docker Swarm service, or Kubernetes deployment (Helm-ready).

### Stories & Tasks
- **Story 1: Dockerize Auto-Healer**
  - Task: Write a production-ready Dockerfile (multi-stage, minimal image) **[COMPLETE]**
  - Task: Add docker-compose.yml for local dev/test **[COMPLETE]**
  - Task: Document environment variables, secrets, and config mounting **[COMPLETE]**
    - Subtask: Add troubleshooting section for container issues **[COMPLETE]**
- **Story 2: Swarm/HA Support**
  - Task: Add health/liveness/readiness endpoints **[COMPLETE]**
  - Task: Document scaling, rolling updates, and service discovery **[COMPLETE]**
- **Story 3: Kubernetes/Helm**
  - Task: Write Kubernetes manifests (Deployment, Service, ConfigMap, Secret) **[COMPLETE]**
  - Task: Create a Helm chart with values.yaml **[COMPLETE]**
  - Task: Document deployment, upgrades, and rollback **[COMPLETE]**

**Phase 9 Estimate:** 10d

---

## Phase 10: Web Dashboard & Self-Service
**Goal:** Provide a UI for action history, approvals, manual triggers, and real-time status.

### Stories & Tasks
- **Story 1: Dashboard MVP**
  - Task: Design UI/UX wireframes _(1d)_
  - Task: Implement dashboard (React/Vue/Svelte) _(5d)_
  - Task: Integrate with API for action listing, approval, and dry-run _(2d)_
- **Story 2: Real-Time Status & Metrics**
  - Task: Add WebSocket or polling for live updates _(2d)_
  - Task: Show action queue, audit log, and notifications _(2d)_
- **Story 3: Self-Service Onboarding**
  - Task: UI for onboarding new actions/scripts _(2d)_
  - Task: Docs and walkthrough _(1d)_

**Phase 10 Estimate:** 15d

---

## Phase 11: Audit, Compliance & Analytics
**Goal:** Provide immutable audit logs, export, and analytics for compliance.

### Stories & Tasks
- **Story 1: Immutable Audit Log Storage**
  - Task: Integrate with S3 or external SIEM _(2d)_
  - Task: Add log rotation and retention policies _(1d)_
- **Story 2: Export & Compliance**
  - Task: Export logs in CSV/JSON formats _(1d)_
  - Task: Add compliance metadata (user, timestamp, action) _(1d)_
- **Story 3: Analytics**
  - Task: Action success/failure rates, trends _(2d)_
  - Task: Dashboard widgets for analytics _(2d)_

**Phase 11 Estimate:** 9d

---

## Phase 12: Security Guardrails
**Goal:** Enforce security best practices, secrets management, and RBAC.

### Stories & Tasks
- **Story 1: Secret Management Integration**
  - Task: Integrate with Vault/AWS Secrets Manager _(2d)_
  - Task: Refactor config to use secrets _(1d)_
- **Story 2: RBAC & API Keys**
  - Task: Per-action/controller API keys _(2d)_
  - Task: Role-based access control for endpoints _(2d)_
- **Story 3: Rate Limiting & Cooldowns**
  - Task: Implement per-action rate limits _(1d)_
  - Task: Add cooldowns and impact simulation _(1d)_

**Phase 12 Estimate:** 9d

---

## Phase 13: Enhanced Notification Integration
**Goal:** Support more platforms, custom templates, and notification routing.

### Stories & Tasks
- **Story 1: Multi-Platform Support**
  - Task: Integrate email, PagerDuty, Opsgenie, SMS _(3d)_
- **Story 2: Custom Templates & Routing**
  - Task: Add notification templates per action/severity _(2d)_
  - Task: Severity-based routing and throttling _(2d)_
- **Story 3: Notification Deduplication**
  - Task: Implement deduplication logic _(1d)_

**Phase 13 Estimate:** 8d

---

## Phase 14: Developer Experience
**Goal:** Improve onboarding, local dev, and action scaffolding.

### Stories & Tasks
- **Story 1: CLI Tool**
  - Task: Build CLI for local testing, dry-run, and action management _(3d)_
- **Story 2: Action Scaffolding**
  - Task: Generator for new actions/scripts _(2d)_
- **Story 3: Docs & Samples**
  - Task: Add code samples and onboarding docs _(1d)_

**Phase 14 Estimate:** 6d

---

## Phase 15: Cloud Provider Integrations
**Goal:** Native support for AWS, Azure, GCP for cloud-native healing.

### Stories & Tasks
- **Story 1: AWS Integration**
  - Task: Trigger Lambda, SSM, EC2 actions _(2d)_
  - Task: CloudWatch event integration _(1d)_
- **Story 2: Azure & GCP**
  - Task: Azure Functions, VM, and alert integration _(2d)_
  - Task: GCP Cloud Functions, Compute Engine _(2d)_
- **Story 3: Cloud Auth & Config**
  - Task: Secure credential/config management _(1d)_

**Phase 15 Estimate:** 9d

---

## Phase 16: Extensibility & Plugins
**Goal:** Allow plugins for custom actions, notifications, and health checks.

### Stories & Tasks
- **Story 1: Plugin System**
  - Task: Design plugin API and loader _(2d)_
  - Task: Implement plugin discovery and sandboxing _(2d)_
- **Story 2: Plugin Marketplace**
  - Task: Registry for community plugins _(2d)_
  - Task: Docs and publishing guide _(1d)_

**Phase 16 Estimate:** 7d
