# Phases for Auto-Healer API Server Implementation

---

## **Phase 1: Project Foundation & Core API**

### **1.1 Project Setup**
- **Story:** Initialize project structure and tooling
  - Task: Set up repository and directory structure (`src/`, `playbooks/`, `scripts/`, `config/`, `logs/`, `tests/`, `docs/`)
    - Subtask: Create root project directory
    - Subtask: Create all required subdirectories
    - Subtask: Add placeholder files (e.g., `.gitkeep`) to empty dirs
  - Task: Initialize Python/Node.js/Go project (choose stack)
    - Subtask: Select language and framework
    - Subtask: Initialize project with package manager (e.g., `pip`, `npm`, `go mod`)
    - Subtask: Add main entrypoint file
  - Task: Set up linting, formatting, and pre-commit hooks
    - Subtask: Choose linter and formatter (e.g., flake8, black, eslint, prettier)
    - Subtask: Add config files for linting/formatting
    - Subtask: Set up pre-commit hooks (e.g., with `pre-commit` or Husky)
  - Task: Add initial `README.md` and documentation
    - Subtask: Write project overview
    - Subtask: Document directory structure
    - Subtask: Add setup and usage instructions

### **1.2 Core API Server**
- **Story:** Implement basic API server with health check
  - Task: Create `/health` endpoint
    - Subtask: Define route and handler
    - Subtask: Return status and version info
    - Subtask: Add test for health endpoint
  - Task: Set up basic server framework (Flask/FastAPI/Express/etc.)
    - Subtask: Install framework dependencies
    - Subtask: Implement server startup logic
    - Subtask: Add config for host/port/env
  - Task: Add structured logging
    - Subtask: Choose logging library
    - Subtask: Configure log format (JSON, timestamps, etc.)
    - Subtask: Add log statements to server startup and health endpoint

---

## **Phase 2: Authentication & Security**

### **2.1 API Authentication**
- **Story:** Secure API endpoints
  - Task: Implement API key/token authentication
    - Subtask: Define API key/token storage (env/config)
    - Subtask: Add middleware to check auth header
    - Subtask: Return 401 on missing/invalid key
    - Subtask: Add tests for auth logic
  - Task: Add middleware for authentication
    - Subtask: Integrate middleware with all protected endpoints
    - Subtask: Ensure health endpoint is public (if desired)
  - Task: Document authentication method
    - Subtask: Add API key/token usage to README
    - Subtask: Document how to generate/rotate keys

### **2.2 Authorization**
- **Story:** Add controller override authorization
  - Task: Define roles/permissions in config
    - Subtask: Design roles/permissions structure in config
    - Subtask: Add example roles (admin, operator, readonly)
  - Task: Enforce permissions for controller overrides
    - Subtask: Implement permission checks in override logic
    - Subtask: Return 403 on unauthorized override
    - Subtask: Add tests for permission enforcement

---

## **Phase 3: Action Mapping & Execution Engine**

### **3.1 Action Mapping**
- **Story:** Map events to actions and controllers
  - Task: Design `actions.yaml` config structure
    - Subtask: Define schema for mapping events to actions/controllers
    - Subtask: Add support for parameters and defaults
    - Subtask: Provide example config
  - Task: Implement config loader and validator
    - Subtask: Write loader to parse YAML/JSON
    - Subtask: Validate config against schema
    - Subtask: Handle config reloads (optional)
  - Task: Support parameterization in mappings
    - Subtask: Allow event payload to override parameters
    - Subtask: Document parameterization in config

### **3.2 Controller Inventory**
- **Story:** Manage controller/client nodes
  - Task: Design `controllers.yaml` structure
    - Subtask: Define schema for controller/client metadata
    - Subtask: Add example entries for Ansible, oc, etc.
  - Task: Implement controller inventory loader
    - Subtask: Write loader to parse controllers config
    - Subtask: Validate controller types and required fields
  - Task: Validate controller existence and type
    - Subtask: Check controller exists before execution
    - Subtask: Return error if controller is missing/invalid

### **3.3 Action Executor**
- **Story:** Execute playbooks/scripts on controllers
  - Task: Implement SSH/API execution logic
    - Subtask: Implement SSH connection logic
    - Subtask: Implement API call logic (if needed)
    - Subtask: Handle connection errors and timeouts
  - Task: Support Ansible playbooks and ad-hoc scripts
    - Subtask: Add logic to run Ansible playbooks via CLI
    - Subtask: Add logic to run shell/Python scripts
    - Subtask: Support passing parameters to playbooks/scripts
  - Task: Capture and return execution output and errors
    - Subtask: Capture stdout/stderr from executions
    - Subtask: Parse and format results for API response
    - Subtask: Log execution details

---

## **Phase 4: Webhook Handling & Dynamic Routing**

### **4.1 Webhook Endpoint**
- **Story:** Handle incoming webhooks
  - Task: Implement `/webhook` endpoint
    - Subtask: Define route and handler
    - Subtask: Accept and parse JSON payloads
    - Subtask: Return 200/400/500 as appropriate
  - Task: Parse and validate payloads
    - Subtask: Define payload schema
    - Subtask: Validate required fields (event_type, target, etc.)
    - Subtask: Return error on invalid payload
  - Task: Extract event type, target, and controller override
    - Subtask: Parse fields from payload
    - Subtask: Pass extracted info to action mapping logic

### **4.2 Dynamic Controller Selection**
- **Story:** Support controller override from webhook
  - Task: Check for `controller_override` in payload
    - Subtask: Parse override field if present
    - Subtask: Validate override value
  - Task: Validate and authorize override
    - Subtask: Check permissions for override
    - Subtask: Return error if not allowed
  - Task: Fallback to default controller if not specified
    - Subtask: Use mapping config if no override
    - Subtask: Log which controller was selected

---

## **Phase 5: Logging, Auditing, and Error Handling**

### **5.1 Structured Logging**
- **Story:** Implement structured and contextual logging
  - Task: Log all requests, actions, controllers, and results
    - Subtask: Add request logging middleware
    - Subtask: Log action execution details
    - Subtask: Log controller selection and overrides
  - Task: Store logs in `logs/` directory
    - Subtask: Configure log file rotation/retention
    - Subtask: Ensure logs are structured (JSON, etc.)

### **5.2 Audit Trail**
- **Story:** Maintain execution audit trail
  - Task: Record action details, user, controller, and outcome
    - Subtask: Define audit log schema
    - Subtask: Write audit entries on every action
  - Task: Implement `/audit` endpoint (secured) for audit retrieval
    - Subtask: Define route and handler
    - Subtask: Secure endpoint with authentication/authorization
    - Subtask: Support filtering by date, action, user

### **5.3 Error Handling**
- **Story:** Robust error handling and reporting
  - Task: Standardize error responses
    - Subtask: Define error response schema
    - Subtask: Return consistent error codes/messages
  - Task: Log errors and failed attempts
    - Subtask: Log all exceptions and failures
    - Subtask: Include context in error logs

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
