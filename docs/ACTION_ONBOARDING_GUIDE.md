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

### Raw Command Example (oc/kubectl-style Actions)
For actions that don't warrant a full playbook or script file - e.g. a
single `oc`/`kubectl` one-liner - use `command:` instead. `{param}`
placeholders are substituted from the action's parameters.
```yaml
restart_deployment:
  command: "oc rollout restart deployment/{deployment} -n {namespace}"
  default_controller: dc2-oc
  parameters:
    namespace: "default"
```
When the target controller isn't local (see "Controller and Remote VM
Access" below), the rendered command is run on the controller over SSH,
with each parameter value shell-quoted first so parameter values can't
break out into arbitrary shell commands.

### Direct Kubernetes API Actions (`kube_action`)
An alternative to the SSH+`oc` approach above: `type: kubeapi` controllers
talk to the Kubernetes/OpenShift API server directly - no SSH, no
`oc`/`kubectl` subprocess. Use this when Auto-Healer runs inside (or has
direct network + RBAC access to) the cluster it's healing, and you want
credentials scoped to exactly the operations needed rather than an `oc`
session's full access.

`kube_action` is a **closed set of verbs**, not a generic "patch anything"
API proxy - each one is a specific, reviewed operation:

| Verb | Does |
|---|---|
| `rollout_restart` | Restarts a Deployment/StatefulSet/DaemonSet (same effect as `oc rollout restart`) |
| `delete_pod` | Deletes a Pod, letting its controller recreate it |
| `scale` | Sets `replicas` on a Deployment/StatefulSet/ReplicaSet |
| `cordon_node` / `uncordon_node` | Marks a Node (un)schedulable |
| `drain_node` | Cordons a Node, then evicts every non-DaemonSet Pod on it (respects PodDisruptionBudgets - a Pod blocked by its PDB is reported as a failure, not silently skipped) |
| `patch_configmap` | Merges new key/value pairs into a ConfigMap's `data` |

```yaml
restart_deployment_kubeapi:
  kube_action: rollout_restart
  resource: deployment          # deployment | statefulset | daemonset
  name: "{deployment}"
  namespace: "{namespace}"
  default_controller: k8s-in-cluster
  parameters:
    namespace: "default"
  cooldown_seconds: 300
  cooldown_key_param: deployment
```
`scale` and `patch_configmap` take their extra values through `data:`
(also `{param}`-templated):
```yaml
scale_deployment:
  kube_action: scale
  resource: deployment
  name: "{deployment}"
  namespace: "{namespace}"
  data:
    replicas: "{replicas}"
```
Node-targeting verbs (`cordon_node`/`uncordon_node`/`drain_node`) use
`node_name:` instead of `name:`/`namespace:` (Nodes are cluster-scoped).

**Controller credentials** - three ways to authenticate, checked in this
order:
```yaml
controllers:
  # 1. In-cluster (recommended when Auto-Healer runs as a Pod in the
  #    cluster it heals): zero credential config. Kubernetes auto-mounts
  #    a ServiceAccount token; RBAC is controlled by which ServiceAccount
  #    the Deployment binds to.
  k8s-in-cluster:
    type: kubeapi
    in_cluster: true

  # 2. Explicit ServiceAccount token + API server (recommended for a
  #    remote cluster - scope the token's RBAC Role narrowly, e.g. patch
  #    on deployments, delete on pods, nothing more):
  k8s-prod:
    type: kubeapi
    api_server: https://api.prod.example.com:6443
    token: "vault:secret/data/auto-healer/clusters/prod#token"
    ca_cert: "vault:secret/data/auto-healer/clusters/prod#ca_cert"

  # 3. A pre-existing kubeconfig, if that's what your platform team
  #    already issues:
  k8s-staging:
    type: kubeapi
    kubeconfig: "vault:secret/data/auto-healer/clusters/staging#kubeconfig"
```
`token`/`ca_cert`/`kubeconfig` all accept the same plain-file-path or
`vault:<path>#<field>` forms as `ssh_key` (see "Secrets via Vault"
below) - never a literal secret value inline. A token/kubeconfig without
`ca_cert` disables TLS verification for that call and logs a warning;
always set `ca_cert` for anything beyond local testing.

All of this plugs into the same cooldowns, rate limits, approval
workflow, RBAC, audit logging, and `dry_run` handling as every other
action type - `dry_run` never builds a Kubernetes client or touches the
API at all.

### Cooldowns (Preventing Repeat Execution)
Add `cooldown_seconds` to an action to stop it being re-triggered too
soon after it last ran - the safety net for a flapping alert that would
otherwise re-run the same remediation every few seconds. Optionally add
`cooldown_key_param`, naming one of the action's parameters, so the
cooldown is scoped per-target instead of blocking the action globally
(e.g. restarting `web` shouldn't block restarting `api`):
```yaml
restart_deployment:
  command: "oc rollout restart deployment/{deployment} -n {namespace}"
  default_controller: dc2-oc
  parameters:
    namespace: "default"
  cooldown_seconds: 300
  cooldown_key_param: deployment
```
While in cooldown, `/webhook` returns `409 Conflict` with
`cooldown_remaining_seconds` in the body, and an audit log entry is still
written (`blocked_reason: "cooldown"`) so the suppression is visible. For
`approval_required` actions, cooldown is checked at approve time, not at
queue time - the request can still be queued, and a blocked approval
leaves the entry `pending` so it can be retried once the cooldown clears.
`dry_run` calls are exempt entirely: they don't check or consume the
cooldown, since they never touch real infrastructure. Actions with no
`cooldown_seconds` configured (the default) are never rate-limited by
this mechanism.

### Rate Limiting (Preventing API Abuse)
Separate from cooldowns, `config/rate_limits.yaml` throttles `/webhook`
itself along two independent dimensions - a request is blocked if either
one is exceeded:
- **Caller limit** - how many `/webhook` calls one API key can make per
  minute. Set per role (`per_role`) with a `default` fallback for roles
  not listed.
- **Action limit** (optional, `per_action`) - how many `/webhook` calls
  for one specific action can happen per minute, across *every* caller.
  Use this for an action that's sensitive enough to cap regardless of who
  (or how many different API keys) is triggering it.
```yaml
default:
  requests_per_minute: 60
per_role:
  readonly: { requests_per_minute: 20 }
per_action:
  restart_deployment: { requests_per_minute: 10 }
```
A blocked call gets `429 Too Many Requests` with a `Retry-After` header
and `retry_after_seconds` in the body, and (like cooldown blocks) still
writes an audit log entry. Unlike cooldowns, rate-limit counters are
in-memory only - a restart naturally resets them, which is fine since
this protects the API from abuse rather than protecting infrastructure
from repeated remediation. Rate limiting applies to `/webhook` only
(both the queue-for-approval and direct-execution paths); it isn't
applied to `/approvals/{id}/approve`, `/approvals/{id}/reject`, or
read-only endpoints.

### Fine-Grained API Key Scoping (RBAC, per key)
Role-based permissions (`controller_override`, `execute_actions`,
`audit_read`, `approvals_read`, `approve_actions` in `config/auth.yaml`)
are the first, coarse layer of access control: they gate what a *role*
can do at all. `readonly` is the one built-in role without
`execute_actions`, so a readonly key gets `403` from `/webhook`
outright, before any action-specific logic runs.

On top of that, an individual API key can be scoped to a specific
allow-list of actions and/or controllers, narrower than what its role
would otherwise permit - useful for handing a single-purpose key (a CI
pipeline, an alerting integration) only the exact capability it needs,
without inventing a whole new role for it:
```yaml
api_keys:
  "admin-key": admin              # unrestricted - the original, still-default shape
  "ci-restart-key":
    role: operator
    allowed_actions: ["restart_deployment", "restart_deployment_kubeapi"]
    allowed_controllers: ["dc1-ansible", "k8s-in-cluster"]
```
`allowed_actions`/`allowed_controllers` are each independently optional;
omitting one (or using the plain-string shape, as `admin-key` does
above) leaves that dimension unrestricted. An empty list (`[]`) is not
the same as omitting it - it denies everything for that dimension.
`allowed_controllers` applies to a resolved controller regardless of how
it was chosen - an action's `default_controller` is checked against it
exactly the same way a `controller_override` is.

This is enforced in three places, all fed by the same
`is_action_allowed_for_key`/`is_controller_allowed_for_key` checks in
`src/auth.py`:
- `/webhook`'s direct-execution path - a disallowed action/controller
  gets `403` immediately, before dry-run or cooldown are even checked.
- `/webhook`'s `approval_required` path - the same checks gate *queuing*
  the request, not just executing it; a key can't get a disallowed
  action into the approval queue for someone else to approve.
- `/approvals/{id}/approve` - the *original requester's* scope (not the
  approver's) is re-checked at approve time, in case `config/auth.yaml`
  changed while the request sat pending. If it's no longer permitted,
  the entry is marked `rejected` with a reason rather than left
  dangling `pending`.

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

### Secrets via Vault (Optional)
Both API keys (`config/auth.yaml`) and controller SSH/kube credentials
(`config/controllers.yaml`) can be resolved from HashiCorp Vault instead
of living in plaintext config, if Vault is configured in the environment
(see "Vault auth methods" below):
```yaml
# config/auth.yaml
api_keys:
  vault_path: "secret/data/auto-healer/api-keys"   # {api_key: role} at this path

# config/controllers.yaml
controllers:
  dc2-oc:
    ssh_key: "vault:secret/data/auto-healer/controllers/dc2-oc"
    # or, for a non-default field name:
    # ssh_key: "vault:secret/data/auto-healer/controllers/dc2-oc#ssh_private_key"
```
Both are opt-in and read-only (KV v2) - a deployment that doesn't
configure Vault behaves exactly as if Vault support didn't exist. If
`vault_path` **is** configured for API keys and Vault becomes
unreachable, every key is rejected (fails closed) rather than falling
back to a stale or empty set - auth silently staying open because a
secrets backend hiccupped would be far worse than a legitimate caller
getting a retryable 401. SSH keys and kube credentials fetched from
Vault are written to a private (`0600`) tempfile for the duration of one
call and deleted immediately after - key material never touches
persistent disk.

#### Vault auth methods
Two ways to authenticate *to* Vault itself are supported, chosen with
`VAULT_AUTH_METHOD`:
- **`token`** (default) - a static token in `VAULT_TOKEN`. Simple, but
  it's a long-lived credential that has to be provisioned and rotated
  out-of-band, same as any other static secret.
- **`kubernetes`** - [Vault's Kubernetes auth
  method](https://developer.hashicorp.com/vault/docs/auth/kubernetes).
  Auto-Healer exchanges its own pod's mounted ServiceAccount JWT for a
  short-lived Vault token by calling `POST /v1/auth/<mount>/login` -
  the same ServiceAccount already used for `in_cluster: true`
  `type: kubeapi` controllers. There's no static Vault credential
  sitting in a Secret or env var at all; the token is re-issued
  automatically before it expires. Configure with:
  ```
  VAULT_ADDR=https://vault.example.com
  VAULT_AUTH_METHOD=kubernetes
  VAULT_K8S_ROLE=auto-healer          # the Vault role bound to this ServiceAccount
  VAULT_K8S_MOUNT_PATH=kubernetes     # optional, defaults to "kubernetes"
  VAULT_K8S_JWT_PATH=/var/run/secrets/kubernetes.io/serviceaccount/token  # optional
  ```
  On the Vault side this requires a `kubernetes` auth mount configured
  with the cluster's API server address and CA, plus a role that binds
  Auto-Healer's ServiceAccount/namespace to the policies it needs
  (typically read on `secret/data/auto-healer/*`). This is the
  recommended method for in-cluster deployments; use `token` for
  deployments running outside Kubernetes.

AppRole auth, AWS Secrets Manager, and dynamic secrets aren't built yet.

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
