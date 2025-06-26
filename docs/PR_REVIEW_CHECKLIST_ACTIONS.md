# PR Review Checklist: New Healing Actions

Use this checklist when reviewing pull requests that add or modify healing actions (playbooks/scripts):

- [ ] Playbook/script is in the correct directory (`playbooks/` or `scripts/`)
- [ ] Script is executable (if applicable)
- [ ] Action is mapped in `config/actions.yaml`
- [ ] Controller exists in `config/controllers.yaml`
- [ ] Action tested via `/webhook` endpoint
- [ ] Documentation/comments are clear and complete
- [ ] All tests and lint checks pass
- [ ] No sensitive data or credentials are committed
- [x] Approval workflow implemented and tested (queue, approve, reject, list)
- [x] Dry-run support implemented and tested
- [x] CI/CD checks: lint, format, test, coverage, security, badge automation, onboarding, README link validation
- [x] Documentation and onboarding guides updated
