import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from jupyter_server.services.kernels.connection.channels import ZMQChannelsWebsocketConnection
from kubernetes.client import ApiException
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from mkm.handlers import default_handlers
from mkm.kernel_manager import KubeMultiKernelManager


def create_mock_kernel_response(kernel_id=None, kernel_name=None, *, ready=True):
    """Helper function to create mock kernel response"""
    if not kernel_id:
        kernel_id = str(uuid.uuid4())
    if not kernel_name:
        kernel_name = f"python-{kernel_id}"

    return {
        "apiVersion": "jupyrator.org/v1",
        "kind": "KernelManager",
        "metadata": {
            "name": kernel_name,
            "namespace": "default",
            "labels": {
                "jupyrator.org/kernel-id": kernel_id,
                "jupyrator.org/kernelmanager-name": f"python-{kernel_id}",
                "jupyrator.org/kernel-spec-name": "python",
            },
            "creationTimestamp": "2024-03-20T10:00:00Z",
        },
        "spec": {
            "idleTimeoutSeconds": 3600,
            "cullingIntervalSeconds": 60,
            "kernelConnectionConfig": {
                "ip": "127.0.0.1",
                "shellPort": 52318,
                "iopubPort": 52317,
                "stdinPort": 52319,
                "controlPort": 52321,
                "hbPort": 52320,
                "kernelId": kernel_id,
                "key": str(uuid.uuid4()),
                "transport": "tcp",
                "signatureScheme": "hmac-sha256",
                "kernelName": "python",
            },
            "template": {
                "spec": {
                    "containers": [
                        {
                            "image": "jupyter/base-notebook:latest",
                            "name": "ipykernel",
                            "workingDir": "/home/jovyan",
                            "env": [],
                            "volumeMounts": [],
                        }
                    ],
                    "volumes": [],
                }
            },
        },
        "status": {"phase": "Running" if ready else "Pending", "ip": "127.0.0.1"},
    }


@pytest.mark.asyncio
class TestKernelHandlers(AsyncHTTPTestCase):
    def setUp(self):
        """Set up test environment and mock kubernetes API"""
        # Create patches for kubernetes API
        self.k8s_config_patcher = patch("kubernetes.config.load_kube_config")
        self.k8s_client_patcher = patch("kubernetes.client.ApiClient")
        self.k8s_custom_api_patcher = patch("kubernetes.client.CustomObjectsApi")

        # Start all patches
        self.k8s_config_patcher.start()
        self.k8s_client_patcher.start()
        mock_custom_api = self.k8s_custom_api_patcher.start()

        # Create and store mock API instance
        self.mock_k8s_api = MagicMock()
        mock_custom_api.return_value = self.mock_k8s_api

        super().setUp()

    def tearDown(self):
        """Clean up patches"""
        self.k8s_config_patcher.stop()
        self.k8s_client_patcher.stop()
        self.k8s_custom_api_patcher.stop()
        super().tearDown()

    def get_app(self):
        """Create a test application"""
        self.kernel_manager = KubeMultiKernelManager()
        return Application(
            handlers=default_handlers,
            kernel_manager=self.kernel_manager,
            kernel_websocket_connection_class=ZMQChannelsWebsocketConnection,
            allow_unauthenticated_access=True,
        )

    def test_list_kernels_empty(self):
        """Test listing kernels when none exist"""
        self.mock_k8s_api.list_cluster_custom_object.return_value = {"items": []}

        response = self.fetch("/api/kernels")
        assert response.code == 200
        kernels = json.loads(response.body)
        assert len(kernels) == 0

    def test_create_kernel(self):
        """Test creating a new kernel"""
        kernel_id = str(uuid.uuid4())
        mock_kernel = create_mock_kernel_response(kernel_id=kernel_id)

        # Mock create response
        self.mock_k8s_api.create_namespaced_custom_object.return_value = None
        # Mock list response for verification
        self.mock_k8s_api.list_namespaced_custom_object.return_value = {"items": [mock_kernel]}

        body = json.dumps({"name": "python"})
        response = self.fetch("/api/kernels", method="POST", body=body, headers={"Content-Type": "application/json"})

        assert response.code == 200
        kernel = json.loads(response.body)
        assert kernel["id"] == kernel_id
        self.mock_k8s_api.create_namespaced_custom_object.assert_called_once()

    def test_get_kernel(self):
        """Test getting a specific kernel"""
        kernel_id = str(uuid.uuid4())
        mock_kernel = create_mock_kernel_response(kernel_id=kernel_id)

        self.mock_k8s_api.list_cluster_custom_object.return_value = {"items": [mock_kernel]}

        response = self.fetch(f"/api/kernels/{kernel_id}")
        assert response.code == 200
        kernel = json.loads(response.body)
        assert kernel["id"] == kernel_id

    def test_delete_kernel(self):
        """Test deleting a kernel"""
        kernel_id = str(uuid.uuid4())
        mock_kernel = create_mock_kernel_response(kernel_id=kernel_id)

        self.mock_k8s_api.list_cluster_custom_object.return_value = {"items": [mock_kernel]}
        self.mock_k8s_api.delete_namespaced_custom_object.return_value = {}

        response = self.fetch(f"/api/kernels/{kernel_id}", method="DELETE")
        assert response.code == 200
        self.mock_k8s_api.delete_namespaced_custom_object.assert_called_once()

    def test_create_kernel_failure(self):
        """Test kernel creation failure"""
        self.mock_k8s_api.create_namespaced_custom_object.side_effect = ApiException(status=400, reason="Bad Request")

        body = json.dumps({"name": "python"})
        response = self.fetch("/api/kernels", method="POST", body=body, headers={"Content-Type": "application/json"})
        assert response.code == 500

    def test_create_kernel_already_exists(self):
        """Test kernel creation failure"""
        self.mock_k8s_api.create_namespaced_custom_object.side_effect = ApiException(status=409, reason="Bad Request")

        body = json.dumps({"name": "python", "env": {"KERNEL_ID": "XXXXX"}})
        response = self.fetch("/api/kernels", method="POST", body=body, headers={"Content-Type": "application/json"})
        assert response.code == 409
        assert "Kernel already exists:" in response.body.decode("utf-8")

    def test_kernel_not_found(self):
        """Test getting a non-existent kernel"""
        # Mock API to raise NotFound exception
        self.mock_k8s_api.list_namespaced_custom_object.side_effect = ApiException(status=404, reason="Not Found")

        response = self.fetch("/api/kernels/nonexistent-id")
        assert response.code == 404

    def test_invalid_json(self):
        """Test sending invalid JSON when creating kernel"""
        response = self.fetch(
            "/api/kernels", method="POST", body="invalid json", headers={"Content-Type": "application/json"}
        )
        assert response.code == 422
