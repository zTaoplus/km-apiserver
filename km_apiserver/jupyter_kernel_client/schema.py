from __future__ import annotations

import datetime
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from km_apiserver.jupyter_kernel_client.constants import KERNEL_ID, KERNEL_LAST_ACTIVITY_TIME


class KernelSpecName(str, Enum):
    """Supported kernel specification names"""

    PYTHON = "python"
    # TODO: not support now
    # R = "r"
    # SCALA = "scala"


class KernelConnectionInfoModel(BaseModel):
    """Model representing kernel connection information.

    This model contains all the necessary connection details for communicating with a Jupyter kernel,
    including ports for different channels, authentication details, and kernel identification.
    """

    ip: str = Field(default="0.0.0.0")  # noqa: S104
    """IP address the kernel is listening on"""

    shell_port: int = Field(default=52318, alias="shellPort")
    """Port number for the shell channel used for request/reply"""

    iopub_port: int = Field(default=52317, alias="iopubPort")
    """Port number for the IOPub channel used for broadcasts"""

    stdin_port: int = Field(default=52319, alias="stdinPort")
    """Port number for the stdin channel used for input requests"""

    control_port: int = Field(default=52321, alias="controlPort")
    """Port number for the control channel used for kernel control"""

    hb_port: int = Field(default=52320, alias="hbPort")
    """Port number for the heartbeat channel used to check kernel status"""

    kernel_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="kernelId")
    """Unique identifier for the kernel"""

    key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Authentication key used to sign messages"""

    transport: str = Field(default="tcp")
    """Transport protocol used for communication"""

    signature_scheme: str = Field(default="hmac-sha256", alias="signatureScheme")
    """Cryptographic signature scheme used for message authentication"""

    kernel_name: str = Field(default="", alias="kernelName")
    """Name of the kernel"""


class KernelPayload(BaseModel):
    """Request input model for kernel creation"""

    kernel_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    kernel_spec_name: KernelSpecName = Field(default=KernelSpecName.PYTHON)
    """Name of the kernel specification to use. Currently only supports 'python'."""

    kernel_working_dir: str = Field(default="/mnt/data")
    """Working directory for the kernel"""

    kernel_namespace: str = Field(default="default")
    """Namespace where the kernel should be created"""

    kernel_volumes: list[dict[str, Any]] = Field(default=[])
    """Volume configurations used by the kernel"""

    kernel_volume_mounts: list[dict[str, Any]] = Field(default=[])
    """Volume mount configurations for the kernel container"""

    kernel_idle_timeout: int = Field(default=3600)
    """Timeout in seconds after which an idle kernel will be culled"""

    @field_validator("kernel_idle_timeout", mode="before")
    @classmethod
    def validate_timeout(cls, value):
        return int(value)

    kernel_connection_info: KernelConnectionInfoModel = Field(default_factory=KernelConnectionInfoModel)
    """Connection information for the kernel"""

    kernel_image: str = Field(default="zjuici/tablegpt-kernel:0.1.1")
    """Container image to use for running the kernel"""


class KernelModel(KernelPayload):
    """Response output model for kernel information"""

    kernel_name: str = ""
    """Name of the kernel"""

    kernel_last_activity_time: str | None = None
    """Timestamp of the last kernel activity"""

    ready: bool = False
    """Current status of the kernel"""

    @classmethod
    # This obj should be a dict from k8s kernel-manager
    def model_validate(cls, obj: Any, **kwargs) -> KernelModel:
        """Custom validation to extract kernel info from dict"""
        if isinstance(obj, dict):
            # Extract kernel name from metadata
            if "metadata" in obj and "name" in obj["metadata"]:
                obj["kernel_name"] = obj["metadata"]["name"]

            if "metadata" in obj and "namespace" in obj["metadata"]:
                obj["kernel_namespace"] = obj["metadata"]["namespace"]

            # the ready get from status phase is Running
            if "status" in obj and "phase" in obj["status"] and obj["status"]["phase"] == "Running":
                obj["ready"] = True

            # Extract kernel_id from metadata labels
            obj["kernel_id"] = obj["metadata"]["labels"][KERNEL_ID]

            # Extract connection info from spec kernelConnectionConfig and update ip from status
            conn_info = KernelConnectionInfoModel(**obj["spec"]["kernelConnectionConfig"]).model_dump(by_alias=True)
            if "ip" in obj.get("status", {}):
                conn_info["ip"] = obj["status"]["ip"]
            obj["kernel_connection_info"] = conn_info

            # kernel envs from the spec container
            kernel_envs = obj["spec"]["template"]["spec"]["containers"][0]["env"]
            obj["kernel_envs"] = kernel_envs

            # kernel volumes from the spec
            kernel_volumes = obj["spec"]["template"]["spec"]["volumes"]
            obj["kernel_volumes"] = kernel_volumes

            # kernel volume mounts from the spec container
            kernel_volume_mounts = obj["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
            obj["kernel_volume_mounts"] = kernel_volume_mounts

            # kernel image from the spec container
            kernel_image = obj["spec"]["template"]["spec"]["containers"][0]["image"]
            obj["kernel_image"] = kernel_image

            # kernel idle timeout from the spec idleTimeoutSeconds
            kernel_idle_timeout = obj["spec"]["idleTimeoutSeconds"]
            obj["kernel_idle_timeout"] = kernel_idle_timeout

            # kernel working dir from the spec container
            kernel_working_dir = obj["spec"]["template"]["spec"]["containers"][0]["workingDir"]
            obj["kernel_working_dir"] = kernel_working_dir

            # kernel last activity time from the metadata annotations
            if KERNEL_LAST_ACTIVITY_TIME not in obj["metadata"].get("annotations", {}):
                # Creation timestamp is already in ISO format with Z timezone
                obj["kernel_last_activity_time"] = obj["metadata"].get("creationTimestamp", None)
            else:
                # Convert activity time to ISO format with UTC timezone
                activity_time = datetime.datetime.strptime(
                    obj["metadata"]["annotations"][KERNEL_LAST_ACTIVITY_TIME] + "Z", "%Y-%m-%d %H:%M:%S.%f%z"
                ).replace(tzinfo=datetime.timezone.utc)

                obj["kernel_last_activity_time"] = activity_time.isoformat()

        return super().model_validate(obj, **kwargs)
