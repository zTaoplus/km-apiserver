from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client import ApiException

from mkm.jupyter_kernel_client import JupyterKernelClient
from mkm.jupyter_kernel_client.excs import (
    KernelCreationError,
    KernelNotFoundError,
    KernelWaitReadyTimeoutError,
    KernelExistsError,
    KernelResourceQuotaExceededError,
)
from mkm.jupyter_kernel_client.schema import KernelPayload, KernelSpecName


def create_mock_api_exception(status, reason, body=None, headers=None):
    h = MagicMock(status=status, reason=reason, data=body)
    if headers:
        h.getheaders.return_value = headers
    return ApiException(status=status, reason=reason, http_resp=h)


@pytest.fixture
def kernel_client():
    return JupyterKernelClient()


@pytest.fixture
def mock_k8s_api():
    """Fixture to handle common kubernetes API mocking"""
    with (
        patch("kubernetes.config.load_kube_config"),
        patch("kubernetes.client.ApiClient"),
        patch("kubernetes.client.CustomObjectsApi") as mock_custom_api,
    ):
        mock_custom_api_instance = MagicMock()
        mock_custom_api.return_value = mock_custom_api_instance
        yield mock_custom_api_instance


@pytest.mark.asyncio
async def test_create_kernel(mock_k8s_api, kernel_client):
    # Setup initial create response
    create_response = None

    # Setup get response for status check
    get_response = {
        "items": [
            {
                "metadata": {
                    "name": "test-kernel",
                    "namespace": "default",
                    "labels": {"jupyrator.org/kernel-id": "test-id"},
                    "creationTimestamp": "2024-01-01T00:00:00Z",
                },
                "status": {"phase": "Running", "ip": "10.0.0.1"},
                "spec": {
                    "kernelConnectionConfig": {
                        "shellPort": 1234,
                        "iopubPort": 1235,
                        "stdinPort": 1236,
                        "controlPort": 1237,
                        "hbPort": 1238,
                        "kernelId": "test-id",
                        "key": "test-key",
                        "transport": "tcp",
                        "signatureScheme": "hmac-sha256",
                    },
                    "idleTimeoutSeconds": 3600,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "env": [],
                                    "image": "zjuici/tablegpt-kernel:0.1.1",
                                    "workingDir": "/home/jovyan",
                                    "volumeMounts": [],
                                }
                            ],
                            "volumes": [],
                        }
                    },
                },
            }
        ]
    }

    mock_k8s_api.create_namespaced_custom_object.return_value = create_response
    mock_k8s_api.list_namespaced_custom_object.return_value = get_response

    payload = KernelPayload(kernel_spec_name=KernelSpecName.PYTHON)
    kernel = await kernel_client.acreate(payload=payload)

    # Verify create was called
    mock_k8s_api.create_namespaced_custom_object.assert_called_once()

    # Verify get was called to check status
    mock_k8s_api.list_namespaced_custom_object.assert_called()

    # Verify final kernel state
    assert kernel.kernel_name == "test-kernel"
    assert kernel.ready


@pytest.mark.asyncio
async def test_create_kernel_failure(mock_k8s_api, kernel_client):
    mock_k8s_api.create_namespaced_custom_object.side_effect = create_mock_api_exception(
        status=400, reason="Bad Request"
    )

    payload = KernelPayload(kernel_spec_name=KernelSpecName.PYTHON)
    with pytest.raises(KernelCreationError):
        await kernel_client.acreate(payload=payload)


@pytest.mark.asyncio
async def test_create_kernel_with_existing_kernel_id(mock_k8s_api, kernel_client):
    mock_k8s_api.create_namespaced_custom_object.side_effect = create_mock_api_exception(status=409, reason="Conflict")

    payload = KernelPayload(kernel_spec_name=KernelSpecName.PYTHON)
    with pytest.raises(KernelExistsError):
        await kernel_client.acreate(payload=payload)


@pytest.mark.asyncio
async def test_create_kernel_with_resource_quota_exceeded(mock_k8s_api, kernel_client):
    mock_k8s_api.create_namespaced_custom_object.side_effect = create_mock_api_exception(
        status=403, reason="Forbidden", body="exceeded quota:"
    )

    payload = KernelPayload(kernel_spec_name=KernelSpecName.PYTHON)
    with pytest.raises(KernelResourceQuotaExceededError):
        await kernel_client.acreate(payload=payload)


@pytest.mark.asyncio
async def test_create_kernel_with_other_forbidden_reason(mock_k8s_api, kernel_client):
    mock_k8s_api.create_namespaced_custom_object.side_effect = create_mock_api_exception(
        status=403, reason="Forbidden", body="other reason"
    )

    payload = KernelPayload(kernel_spec_name=KernelSpecName.PYTHON)
    with pytest.raises(KernelCreationError):
        await kernel_client.acreate(payload=payload)


@pytest.mark.asyncio
async def test_get_kernel_success(mock_k8s_api, kernel_client):
    mock_response = {
        "items": [
            {
                "metadata": {
                    "name": "test-kernel",
                    "namespace": "default",
                    "labels": {"jupyrator.org/kernel-id": "test-id"},
                    "creationTimestamp": "2024-01-01T00:00:00Z",
                },
                "status": {"phase": "Running", "ip": "10.0.0.1"},
                "spec": {
                    "kernelConnectionConfig": {
                        "shellPort": 1234,
                        "iopubPort": 1235,
                        "stdinPort": 1236,
                        "controlPort": 1237,
                        "hbPort": 1238,
                        "kernelId": "test-id",
                        "key": "test-key",
                        "transport": "tcp",
                        "signatureScheme": "hmac-sha256",
                    },
                    "idleTimeoutSeconds": 3600,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "env": [],
                                    "image": "zjuici/tablegpt-kernel:0.1.1",
                                    "workingDir": "/home/jovyan",
                                    "volumeMounts": [],
                                }
                            ],
                            "volumes": [],
                        }
                    },
                },
            }
        ]
    }
    mock_k8s_api.list_namespaced_custom_object.return_value = mock_response

    kernel = await kernel_client.aget_kernel_by_id("test-id", namespace="default")
    assert kernel.kernel_name == "test-kernel"
    assert kernel.ready


@pytest.mark.asyncio
async def test_list_kernels(mock_k8s_api, kernel_client):
    mock_k8s_api.list_namespaced_custom_object.return_value = {"items": []}

    kernels = await kernel_client.alist(namespace="default")
    mock_k8s_api.list_namespaced_custom_object.assert_called_once()
    assert len(kernels) == 0


@pytest.mark.asyncio
async def test_delete_kernel(mock_k8s_api, kernel_client):
    # should mock the get response first
    mock_k8s_api.list_namespaced_custom_object.return_value = {
        "items": [
            {
                "metadata": {
                    "name": "test-kernel",
                    "namespace": "default",
                    "labels": {"jupyrator.org/kernel-id": "test-id"},
                    "creationTimestamp": "2024-01-01T00:00:00Z",
                },
                "status": {
                    "phase": "Running",
                },
                "spec": {
                    "kernelConnectionConfig": {},
                    "idleTimeoutSeconds": 3600,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "env": [],
                                    "image": "zjuici/tablegpt-kernel:0.1.1",
                                    "workingDir": "/home/jovyan",
                                    "volumeMounts": [],
                                }
                            ],
                            "volumes": [],
                        }
                    },
                },
            }
        ]
    }
    mock_k8s_api.delete_namespaced_custom_object.return_value = {}

    await kernel_client.adelete_by_kernel_id("test-id", namespace="default")
    mock_k8s_api.delete_namespaced_custom_object.assert_called_once()


@pytest.mark.asyncio
async def test_get_kernel_not_found(mock_k8s_api, kernel_client):
    mock_k8s_api.list_namespaced_custom_object.return_value = {"items": []}

    with pytest.raises(KernelNotFoundError):
        await kernel_client.aget_kernel_by_id("nonexistent-id", namespace="default")


@pytest.mark.asyncio
async def test_create_kernel_timeout(mock_k8s_api, kernel_client):
    # Setup responses where status remains "Pending"
    create_response = None

    get_response = {
        "items": [
            {
                "metadata": {
                    "name": "test-kernel",
                    "namespace": "default",
                    "labels": {"jupyrator.org/kernel-id": "test-id"},
                    "creationTimestamp": "2024-01-01T00:00:00Z",
                },
                "status": {
                    "phase": "Pending",
                },
                "spec": {
                    "kernelConnectionConfig": {},
                    "idleTimeoutSeconds": 3600,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "env": [],
                                    "image": "zjuici/tablegpt-kernel:0.1.1",
                                    "workingDir": "/home/jovyan",
                                    "volumeMounts": [],
                                }
                            ],
                            "volumes": [],
                        }
                    },
                },
            }
        ]
    }

    mock_k8s_api.create_namespaced_custom_object.return_value = create_response
    mock_k8s_api.list_namespaced_custom_object.return_value = get_response

    payload = KernelPayload(kernel_spec_name=KernelSpecName.PYTHON)
    with pytest.raises(KernelWaitReadyTimeoutError):
        await kernel_client.acreate(payload=payload, timeout=1, namespace="default")
