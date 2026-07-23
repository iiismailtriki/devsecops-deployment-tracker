# DevSecOps Deployment Tracker

A learning and portfolio project demonstrating a secure CI/CD pipeline for a
Python Flask application.

## Current features

- Flask REST API
- Health endpoint
- Version and deployment metadata
- Environment-based configuration
- Python virtual environment
- Ruff code-quality checks
- Bandit static security analysis
- pip-audit dependency scanning

## API endpoints

| Endpoint | Purpose |
|---|---|
| `/` | Service status |
| `/health` | Application health |
| `/version` | Version and build information |
| `/info` | Complete deployment information |

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
flask --app app.main run --host=0.0.0.0 --port=5000
