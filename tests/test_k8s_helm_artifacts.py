import os
import yaml


def test_k8s_deployment_yaml_exists_and_valid():
    path = os.path.join("k8s", "deployment.yaml")
    assert os.path.exists(path), "k8s/deployment.yaml missing"
    with open(path) as f:
        data = yaml.safe_load(f)
    assert data["kind"] == "Deployment"
    assert data["spec"]["replicas"] >= 1
    assert any(
        c["name"] == "auto-healer"
        for c in data["spec"]["template"]["spec"]["containers"]
    )


def test_k8s_service_yaml_exists_and_valid():
    path = os.path.join("k8s", "service.yaml")
    assert os.path.exists(path), "k8s/service.yaml missing"
    with open(path) as f:
        data = yaml.safe_load(f)
    assert data["kind"] == "Service"
    assert data["spec"]["ports"][0]["port"] == 8000


def test_k8s_configmap_yaml_exists_and_valid():
    path = os.path.join("k8s", "configmap.yaml")
    assert os.path.exists(path), "k8s/configmap.yaml missing"
    with open(path) as f:
        data = yaml.safe_load(f)
    assert data["kind"] == "ConfigMap"
    assert "actions.yaml" in data["data"]


def test_k8s_secret_yaml_exists_and_valid():
    path = os.path.join("k8s", "secret.yaml")
    assert os.path.exists(path), "k8s/secret.yaml missing"
    with open(path) as f:
        data = yaml.safe_load(f)
    assert data["kind"] == "Secret"
    assert "api-key" in data["data"]


def test_helm_chart_yaml_exists_and_valid():
    path = os.path.join("helm", "Chart.yaml")
    assert os.path.exists(path), "helm/Chart.yaml missing"
    with open(path) as f:
        data = yaml.safe_load(f)
    assert data["name"] == "auto-healer"
    assert data["apiVersion"] == "v2"


def test_helm_values_yaml_exists_and_valid():
    path = os.path.join("helm", "values.yaml")
    assert os.path.exists(path), "helm/values.yaml missing"
    with open(path) as f:
        data = yaml.safe_load(f)
    assert data["replicaCount"] >= 1
    assert data["image"]["repository"]
    assert data["service"]["port"] == 8000
