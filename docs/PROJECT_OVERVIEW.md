# Project Overview

Auto-Healer API Server is a modular, production-ready API server for automated remediation and healing actions, supporting Ansible playbooks, ad-hoc scripts, and multi-controller environments.

## Directory Structure

- `src/` - Application source code
- `playbooks/` - Ansible playbooks for remediation
- `scripts/` - Shell/Python scripts for ad-hoc actions
- `config/` - Configuration files (action mapping, controllers, etc.)
- `logs/` - Structured logs and audit trails
- `tests/` - Unit and integration tests
- `docs/` - Documentation

## Setup and Usage Instructions

1. **Create and activate a Python virtual environment:**
   ```zsh
   python3 -m venv venv
   source venv/bin/activate
   ```
2. **Install dependencies:**
   ```zsh
   pip install -r requirements.txt
   ```
3. **Run the API server:**
   ```zsh
   uvicorn src.main:app --reload
   ```
4. **Pre-commit hooks:**
   - Pre-commit hooks are set up for linting and formatting. To run them manually:
     ```zsh
     pre-commit run --all-files
     ```

## API authentication documentation

### API Key Authentication

All endpoints (except `/health`) require an API key for access. The API key must be provided in the `x-api-key` HTTP header.

- To set the API key, use the `API_KEY` environment variable when starting the server.
- Example usage:
  ```bash
  curl -H "x-api-key: changeme" http://localhost:8000/your-endpoint
  ```
- The default API key is `changeme`. **Change this in production!**

### Rotating API Keys
- Update the `API_KEY` environment variable and restart the server.

## Remote Action Execution: Controller and VM Access

- The Auto-Healer API server connects to an Ansible controller node using connection details defined in `config/actions.yaml` or `config/controllers.yaml`.
- The Ansible controller is responsible for connecting to the remote VM, using SSH user/key and other details from its own inventory or playbook variables.
- This separation allows secure, flexible, and environment-specific execution.

**Example controller config:**
```yaml
controllers:
  dc1-ansible:
    host: ansible-controller.example.com
    ssh_user: ansible
    ssh_key: /path/to/key
```
**Example Ansible inventory:**
```
[webservers]
vm1.example.com ansible_user=ubuntu ansible_ssh_private_key_file=/keys/ubuntu.pem
```

**Key Points:**
- Auto-Healer only needs to know how to reach the controller.
- The controller manages all details for connecting to remote VMs.

## Specifying Actions, Target Nodes, and Controllers

- Users call the API with the action name, parameters (such as `target_node`), and optionally the controller.
- If the controller is not specified, the default for the action is used.
- The controller receives the parameters and uses its own inventory to connect to the correct VM.

**Example API Payload:**
```json
{
  "action": "restart_service",
  "parameters": {
    "service_name": "nginx",
    "target_node": "vm1.example.com"
  },
  "controller": "dc1-ansible"
}
```

| What User Provides | Where It Goes         | Who Uses It                |
|--------------------|----------------------|----------------------------|
| action             | API payload          | Auto-Healer                |
| parameters         | API payload          | Passed to controller/playbook |
| controller         | API payload (optional) | Auto-Healer (for routing)  |

## Contributing
- Add new playbooks/scripts in their respective directories and update config.
- Use pre-commit hooks for linting and formatting.

## Approval, Dry-run, and CI/CD Features
- Approval workflow and dry-run support are implemented and documented.
- CI/CD pipeline includes lint, format, test, coverage, security, badge automation, onboarding, and README link validation.
- See README.md for API usage and badge automation details.

---
