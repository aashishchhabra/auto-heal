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
    - Subtask: Write Ansible playbook for service restart
    - Subtask: Add example mapping in config
    - Subtask: Test playbook execution
  - Task: Add script to clean up disk space
    - Subtask: Write shell/Python script for disk cleanup
    - Subtask: Add example mapping in config
    - Subtask: Test script execution
  - Task: Add health check script/playbook
    - Subtask: Write health check script/playbook
    - Subtask: Add example mapping in config
    - Subtask: Test health check execution

### **6.2 Onboarding New Actions**
- **Story:** Enable modular onboarding via GitOps/CI
  - Task: Document process for adding new playbooks/scripts
    - Subtask: Write onboarding guide in `docs/`
    - Subtask: Add PR review checklist for new actions
  - Task: Auto-discover new actions from `playbooks/` and `scripts/`
    - Subtask: Implement directory scan logic
    - Subtask: Update config loader to support auto-discovery

---

## **Phase 7: Notifications & Advanced Features**

### **7.1 Notification Hooks**
- **Story:** Integrate with Slack/Teams for notifications
  - Task: Add notification config
    - Subtask: Define notification settings in config
    - Subtask: Add example for Slack/Teams
  - Task: Implement notification sending on action execution/failure
    - Subtask: Integrate with Slack/Teams API
    - Subtask: Send notifications on success/failure
    - Subtask: Add tests for notification logic

### **7.2 Approval & Dry-Run**
- **Story:** Add approval and dry-run capabilities
  - Task: Implement approval workflow (manual or chatops)
    - Subtask: Define approval process and states
    - Subtask: Integrate with chatops or web UI for approvals
    - Subtask: Block execution until approved
  - Task: Add dry-run mode for actions
    - Subtask: Implement dry-run logic in executor
    - Subtask: Allow dry-run via API or config
    - Subtask: Return simulated results

---

## **Phase 8: Testing, CI/CD, and Documentation**

### **8.1 Testing**
- **Story:** Ensure code quality and reliability
  - Task: Write unit and integration tests
    - Subtask: Write unit tests for all modules
    - Subtask: Write integration tests for API endpoints
    - Subtask: Add tests for error and edge cases
  - Task: Add test cases for all endpoints and scenarios
    - Subtask: Define test scenarios for each endpoint
    - Subtask: Automate test execution in CI

### **8.2 CI/CD Integration**
- **Story:** Automate build, test, and deployment
  - Task: Set up CI/CD pipeline
    - Subtask: Choose CI/CD tool (GitHub Actions, GitLab CI, etc.)
    - Subtask: Configure build, test, and deploy stages
    - Subtask: Add status badges to README
  - Task: Automate onboarding of new actions via PRs
    - Subtask: Add CI checks for new playbooks/scripts
    - Subtask: Validate config and action files in PRs

### **8.3 Documentation**
- **Story:** Comprehensive user and developer docs
  - Task: Document API endpoints, config, and onboarding
    - Subtask: Write API reference docs
    - Subtask: Document config file formats and examples
    - Subtask: Add onboarding guide for new users
  - Task: Provide usage examples and troubleshooting guide
    - Subtask: Add example webhook payloads
    - Subtask: Document common issues and solutions

---

# **Summary Table**

| Phase | Sub-Phase | Story | Tasks |
|-------|-----------|-------|-------|
| 1     | 1.1, 1.2  | Project setup, Core API | Repo, structure, health endpoint, logging |
| 2     | 2.1, 2.2  | AuthN/AuthZ | API key, permissions, docs |
| 3     | 3.1-3.3   | Action mapping, Controller inventory, Executor | Configs, loader, SSH/API exec |
| 4     | 4.1, 4.2  | Webhook, Dynamic routing | Endpoint, override logic |
| 5     | 5.1-5.3   | Logging, Audit, Error handling | Structured logs, audit, error responses |
| 6     | 6.1, 6.2  | Sample actions, Onboarding | Playbooks/scripts, docs, auto-discovery |
| 7     | 7.1, 7.2  | Notifications, Approval, Dry-run | Slack, approval, dry-run |
| 8     | 8.1-8.3   | Testing, CI/CD, Docs | Tests, pipeline, documentation |

---

This phased plan ensures a modular, secure, and extensible implementation.
