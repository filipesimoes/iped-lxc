from typing import Optional
from pydantic import BaseModel, Field


class InstanceStart(BaseModel):
    vmid: int = Field(
        ..., 
        description="The Proxmox VMID of the pre-configured LXC container"
    )
    iped_api_key: str = Field(
        ...,
        description="The API Key required by Nginx inside this container instance."
    )
    proxmox_node: str = Field(
        ...,
        description="The Proxmox node where the container is located."
    )
    proxmox_bridge: str = Field(
        ...,
        description="The network bridge interface for the container."
    )




class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: Optional[str] = None
    token: Optional[str] = None
    vmid: Optional[int] = None
    proxy_url: Optional[str] = None
    container_data_path: Optional[str] = None


class SessionState(BaseModel):
    vmid: int
    node: str
    lxc_ip: str
    iped_api_key: Optional[str] = None
    data_path: Optional[str] = None
    container_data_path: Optional[str] = None
    created_at: float

