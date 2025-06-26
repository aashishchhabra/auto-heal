# Containerization & Orchestration Guide

## Running Auto-Healer in Docker

### Build the Docker image
```sh
docker build -t auto-heal .
```

### Run with Docker
```sh
docker run -d -p 8000:8000 \
  -v $(pwd)/config:/app/config:ro \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/playbooks:/app/playbooks:ro \
  -v $(pwd)/scripts:/app/scripts:ro \
  --env-file .env \
  --name auto-heal auto-heal
```

### Run with Docker Compose
```sh
docker-compose up --build
```

## Environment Variables
- `PYTHONUNBUFFERED=1` (default)
- Add any secrets or config as environment variables or mount as files in `/app/config`.

## Configuration & Secrets
- Mount your `config/`, `playbooks/`, and `scripts/` directories as read-only for best security.
- Use Docker secrets or Kubernetes secrets for sensitive values in production.

## Health, Liveness & Readiness Endpoints

- `/health`: General health check (returns status/version)
- `/live`: Liveness probe for Kubernetes/Swarm (returns status/version)
- `/ready`: Readiness probe for Kubernetes/Swarm (returns status/version)

All three endpoints are public and lightweight, suitable for use in container orchestration probes.

## Kubernetes Deployment

Kubernetes manifests are provided in the `k8s/` directory:
- `deployment.yaml`: Main Deployment resource
- `service.yaml`: ClusterIP Service
- `configmap.yaml`: Mounts config files
- `secret.yaml`: Stores API key (base64-encoded)

Apply with:
```zsh
kubectl apply -f k8s/
```

## Helm Chart

A Helm chart is provided in the `helm/` directory. To install:
```zsh
helm install auto-healer ./helm --set env.API_KEY=<your-api-key>
```

See `helm/templates/NOTES.txt` for upgrade, rollback, and config instructions.

## Helm Chart Details

- Chart, values, and templates are in `helm/`.
- Install: `helm install auto-healer ./helm --set env.API_KEY=<your-api-key>`
- Upgrade: `helm upgrade auto-healer ./helm`
- Rollback: `helm rollback auto-healer <REVISION>`
- Uninstall: `helm uninstall auto-healer`
- See `helm/templates/NOTES.txt` for more.

## Best Practices
- Use `/live` and `/ready` for liveness/readiness probes in your Deployment.
- Store secrets (API keys) in Kubernetes Secrets, not ConfigMaps.
- Mount config files via ConfigMap for easy updates.
- Use rolling updates for zero-downtime deployments.

## Scaling, Rolling Updates, and Service Discovery

- **Scaling:**
  - Edit `replicas` in `k8s/deployment.yaml` or `values.yaml` in Helm.
  - Example: `kubectl scale deployment/auto-healer --replicas=3`
- **Rolling Updates:**
  - Supported by default in Kubernetes. Update image/tag and apply changes.
  - Helm: `helm upgrade auto-healer ./helm --set image.tag=<new-tag>`
- **Service Discovery:**
  - Access via `auto-healer` service in-cluster, or expose via Ingress/LoadBalancer as needed.

For more, see the manifests and chart templates.

## Troubleshooting Container Issues

- **Container won't start:**
  - Check logs with `docker logs <container>` or `kubectl logs <pod>`.
  - Ensure all required config files are mounted and readable.
  - Verify environment variables (e.g., `API_KEY`) are set.
  - Confirm the image was built successfully and is up-to-date.

- **Permission errors:**
  - Make sure mounted files and directories have correct permissions for the container user.
  - Use `chmod` or `chown` as needed on host files before mounting.

- **Config changes not picked up:**
  - If using Docker Compose, restart the service: `docker-compose restart`.
  - In Kubernetes, update the ConfigMap/Secret and restart the pod: `kubectl rollout restart deployment/auto-healer`.

- **Health/liveness/readiness probe failures:**
  - Check that `/health`, `/live`, and `/ready` endpoints are accessible inside the container.
  - Ensure the container port matches the probe configuration.

- **Networking issues:**
  - Verify service and port mappings in Compose or Kubernetes Service.
  - Use `docker exec` or `kubectl exec` to debug inside the container.

- **Image pull errors:**
  - Confirm the image name and tag are correct.
  - If using a private registry, ensure credentials are configured.

For more help, see the logs and consult the README or open an issue.
