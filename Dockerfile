# syntax=docker/dockerfile:1

# --- Builder stage ---
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --user -r requirements.txt

# --- Final image ---
FROM python:3.12-slim
WORKDIR /app
# openssh-client provides `ssh`, used by ActionExecutor.run_remote to reach
# remote controllers (Ansible control nodes / oc-configured hosts).
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
COPY . .
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
