# Onboarding New Healing Actions (Playbooks/Scripts)

## Overview
This guide explains how to add new healing actions (Ansible playbooks or scripts) to the Auto-Healer system in a modular, GitOps-friendly way.

## Steps

1. **Add Your Playbook or Script**
   - Place new Ansible playbooks in the `playbooks/` directory.
   - Place new shell or Python scripts in the `scripts/` directory.
   - Ensure scripts are executable (`chmod +x`).

2. **Update Action Mapping**
   - Edit `config/actions.yaml` to add a new entry for your action.
   - Specify the playbook or script path, default controller, and any parameters.
   - Example:
     ```yaml
     my_restart_action:
       playbook: playbooks/my_restart.yml
       default_controller: ansible_local
       parameters:
         service_name: "myservice"
     my_cleanup_action:
       script: scripts/my_cleanup.sh
       default_controller: local
     ```

3. **Update Controller Inventory (if needed)**
   - If your action requires a new controller, add it to `config/controllers.yaml`.

4. **Test Your Action**
   - Use the `/webhook` endpoint to trigger your action and verify execution.
   - Check logs and audit trail for results.

5. **Submit a Pull Request**
   - Ensure your code passes all tests and lint checks.
   - Follow the PR checklist below.

## PR Review Checklist for New Actions
- [ ] Playbook/script is placed in the correct directory
- [ ] Script is executable (if applicable)
- [ ] Action is mapped in `config/actions.yaml`
- [ ] Controller exists in `config/controllers.yaml`
- [ ] Action tested via `/webhook` endpoint
- [ ] Documentation/comments are clear
- [ ] All tests and lint checks pass

---

## Advanced Examples

### Parameterized Playbook Example
```yaml
restart_nginx:
  playbook: playbooks/restart_service.yml
  default_controller: ansible_local
  parameters:
    service_name: "nginx"
    state: "restarted"
```

### Script with Arguments Example
```yaml
cleanup_tmp:
  script: scripts/cleanup_disk.sh
  default_controller: local
  parameters:
    path: "/tmp"
    min_free_gb: 2
```

### Custom Output Parsing (Optional)
If your script/playbook outputs JSON or custom text, document the expected output format in comments or the PR description. This helps reviewers and users understand the result structure.

---

## Troubleshooting Onboarding

- **Action not appearing?**
  - Ensure the file is in `playbooks/` or `scripts/` and has the correct extension.
  - Check for typos in `config/actions.yaml`.
  - If using auto-discovery, ensure the file is not ignored by `.gitignore` or CI filters.
- **Script not executable?**
  - Run `chmod +x scripts/your_script.sh`.
- **Controller errors?**
  - Verify the controller exists in `config/controllers.yaml` and is reachable.
- **Test failures?**
  - Run `pytest` and check logs for details.
- **Auto-discovery issues?**
  - The system auto-discovers actions at startup. If a new file is not picked up, restart the server or check for errors in logs.

---

## Notes on Auto-Discovery and Config Priority
- Actions in `config/actions.yaml` override auto-discovered actions with the same name.
- Auto-discovery scans `playbooks/` and `scripts/` for new files at startup.
- For advanced onboarding, see `docs/PROJECT_OVERVIEW.md` and integration test examples.

---

## Approval Workflow
- Actions can be queued for approval, listed, approved, or rejected via API endpoints.
- See API usage examples in the main README.

## Dry-Run Support
- All actions support a `dry_run` parameter for safe simulation.
- See API usage examples in the main README.

## Onboarding Checklist
- Ensure new actions implement approval and dry-run logic as required.
- Update tests and documentation for new features.

---

## Controller and Remote VM Access

- When onboarding a new action, specify the controller node in the action config (e.g., `config/actions.yaml`).
- The controller node's connection details (host, user, key) are managed in the controller config.
- The SSH user/key for the remote VM should be managed in the Ansible inventory or playbook variables on the controller node, not in Auto-Healer.

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

This ensures a clear separation of responsibilities and secure credential management.

---

## Specifying Action, Target Node, and Controller

- When triggering an action, users provide the action name, parameters (such as `target_node`), and optionally the controller in the API payload.
- If the controller is omitted, the default for the action is used.
- The controller uses the parameters and its inventory to connect to the correct VM.

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

For more details, see `docs/PROJECT_OVERVIEW.md`.
