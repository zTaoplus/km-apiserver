import json
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from km_apiserver.jupyter_kernel_client.schema import KernelPayload, KernelSpecName


class AliasKernelPayload(KernelPayload):
    """Request input model for kernel creation"""

    # KernelPayload built-in fields
    kernel_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="KERNEL_ID")
    kernel_spec_name: KernelSpecName = Field(default=KernelSpecName.PYTHON, alias="KERNEL_SPEC_NAME")
    kernel_working_dir: str = Field(default="/mnt/data", alias="KERNEL_WORKING_DIR")
    kernel_namespace: str = Field(default="default", alias="KERNEL_NAMESPACE")
    kernel_volumes: list[dict[str, Any]] = Field(default=[], alias="KERNEL_VOLUMES")
    kernel_volume_mounts: list[dict[str, Any]] = Field(default=[], alias="KERNEL_VOLUME_MOUNTS")

    @field_validator("kernel_volumes", "kernel_volume_mounts", mode="before")
    @classmethod
    def validate_json_str(cls, value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    error_msg = "KERNEL_VOLUME_MOUNTS and KERNEL_VOLUMES must be a JSON array"
                    raise TypeError(error_msg)
            except json.JSONDecodeError as e:
                error_msg = "KERNEL_VOLUME_MOUNTS and KERNEL_VOLUMES must be a valid JSON string"
                raise ValueError(error_msg) from e

            return parsed

        return value

    kernel_idle_timeout: int = Field(default=3600, alias="KERNEL_IDLE_TIMEOUT")
    kernel_image: str = Field(default="zjuici/tablegpt-kernel:0.1.1", alias="KERNEL_IMAGE")

    # user request
    kernel_language: str = Field(default="python", alias="KERNEL_LANGUAGE")
    kernel_username: str = Field(default="default", alias="KERNEL_USERNAME")


class CreateKernelPayload(BaseModel):
    name: KernelSpecName = KernelSpecName.PYTHON
    env: dict = Field(default_factory=dict)


class KernelResponse(BaseModel):
    id: str = Field(alias="kernel_id")
    name: str = Field(alias="kernel_name")
    last_activity: str = Field(alias="kernel_last_activity_time")
    execution_state: str = Field(alias="ready", default="starting")

    @field_validator("execution_state", mode="before")
    @classmethod
    def validate_ready_state(cls, value: bool) -> str:  # noqa: FBT001
        if isinstance(value, bool):
            return "idle" if value else "starting"
        return value

    connections: int = Field(alias="kernel_connections", default=0)

    class Config:
        from_attributes = True
