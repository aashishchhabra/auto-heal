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
For more details, see `docs/PROJECT_OVERVIEW.md`.
