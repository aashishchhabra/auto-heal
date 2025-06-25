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

## Contributing
- Add new playbooks/scripts in their respective directories and update config.
- Use pre-commit hooks for linting and formatting.

---
