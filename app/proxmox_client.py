import logging
import os
import time
from abc import ABC, abstractmethod
from proxmoxer import ProxmoxAPI
from app.config import settings

logger = logging.getLogger(__name__)


class BaseProxmoxClient(ABC):
    @abstractmethod
    def start_container(self, node: str, vmid: int) -> None:
        """Starts the LXC container."""
        pass

    @abstractmethod
    def stop_container(self, node: str, vmid: int) -> None:
        """Stops the LXC container."""
        pass

    @abstractmethod
    def get_container_ip(self, node: str, vmid: int, timeout: int = 60) -> str:
        """Polls and returns the container IP address."""
        pass

    @abstractmethod
    def wait_for_task(self, node: str, upid: str, timeout: int = 300) -> None:
        """Waits for a Proxmox task (UPID) to complete."""
        pass


class ProxmoxVEClient(BaseProxmoxClient):
    def __init__(self):
        # Initialize proxmoxer API client
        if settings.PROXMOX_TOKEN_NAME and settings.PROXMOX_TOKEN_VALUE:
            self.client = ProxmoxAPI(
                settings.PROXMOX_HOST,
                port=settings.PROXMOX_PORT,
                user=settings.PROXMOX_USER,
                token_name=settings.PROXMOX_TOKEN_NAME,
                token_value=settings.PROXMOX_TOKEN_VALUE,
                verify_ssl=settings.PROXMOX_VERIFY_SSL
            )
        else:
            self.client = ProxmoxAPI(
                settings.PROXMOX_HOST,
                port=settings.PROXMOX_PORT,
                user=settings.PROXMOX_USER,
                password=settings.PROXMOX_PASSWORD,
                verify_ssl=settings.PROXMOX_VERIFY_SSL
            )
        logger.info("Initialized Proxmox VE API Client")

    def wait_for_task(self, node: str, upid: str, timeout: int = 300) -> None:
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.client.nodes(node).tasks(upid).status.get()
            if status.get("status") == "stopped":
                exitstatus = status.get("exitstatus")
                if exitstatus == "OK":
                    logger.info(f"Proxmox task {upid} completed successfully.")
                    return
                else:
                    raise Exception(f"Proxmox task {upid} failed with status: {exitstatus}")
            time.sleep(1)
        raise TimeoutError(f"Timed out waiting for Proxmox task {upid} after {timeout} seconds.")

    def start_container(self, node: str, vmid: int) -> None:
        logger.info(f"Starting LXC container {vmid}...")
        try:
            status = self.client.nodes(node).lxc(vmid).status.current.get()
            if status.get("status") == "running":
                logger.info(f"Container {vmid} is already running.")
                return
        except Exception as e:
            logger.warning(f"Could not check container status before starting: {e}")

        upid = self.client.nodes(node).lxc(vmid).status.start.post()
        self.wait_for_task(node, upid)

    def stop_container(self, node: str, vmid: int) -> None:
        logger.info(f"Stopping LXC container {vmid}...")
        try:
            upid = self.client.nodes(node).lxc(vmid).status.stop.post()
            self.wait_for_task(node, upid)
        except Exception as e:
            logger.warning(f"Error stopping container {vmid} (might be already stopped): {e}")

    def get_container_ip(self, node: str, vmid: int, timeout: int = 60) -> str:
        logger.info(f"Polling container {vmid} for IP address...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                interfaces = self.client.nodes(node).lxc(vmid).interfaces.get()
                for interface in interfaces:
                    # Ignore loopback interface
                    if interface.get("name") == "lo":
                        continue
                    inet = interface.get("inet")
                    if inet:
                        # inet is typically "192.168.1.150/24" - strip the netmask
                        ip = inet.split("/")[0]
                        if ip:
                            logger.info(f"Found IP {ip} for container {vmid}")
                            return ip
            except Exception as e:
                logger.debug(f"Error checking interfaces for VMID {vmid}: {e}")
            time.sleep(2)
        raise TimeoutError(f"Timed out waiting for container {vmid} to acquire an IP address.")


class MockProxmoxClient(BaseProxmoxClient):
    def __init__(self):
        self.containers = {}
        logger.info("Initialized Mock Proxmox API Client")

    def wait_for_task(self, node: str, upid: str, timeout: int = 300) -> None:
        time.sleep(1)  # Simulate some latency

    def start_container(self, node: str, vmid: int) -> None:
        logger.info(f"[MOCK] Starting container {vmid}")
        if vmid not in self.containers:
            self.containers[vmid] = {
                "status": "stopped",
                "hostname": f"iped-lxc-{vmid}",
                "mounts": {},
                "ip": None
            }
        self.containers[vmid]["status"] = "running"
        # In mock mode, we use localhost or mock-iped container name depending on host environment
        # In docker-compose, mock-iped will be the service hostname. If running outside docker, we use localhost.
        # We can check if settings.MOCK_MODE points to a docker environment or localhost.
        # For testing convenience, we'll return "mock-iped" if we're in a docker container, otherwise "127.0.0.1".
        if os.path.exists("/.dockerenv"):
            self.containers[vmid]["ip"] = "mock-iped"
        else:
            self.containers[vmid]["ip"] = "127.0.0.1"

    def stop_container(self, node: str, vmid: int) -> None:
        logger.info(f"[MOCK] Stopping container {vmid}")
        if vmid in self.containers:
            self.containers[vmid]["status"] = "stopped"

    def get_container_ip(self, node: str, vmid: int, timeout: int = 60) -> str:
        time.sleep(2)  # Simulate startup network delay
        if vmid in self.containers:
            ip = self.containers[vmid]["ip"]
            if ip:
                return ip
        return "127.0.0.1"


def get_proxmox_client() -> BaseProxmoxClient:
    """Returns the appropriate Proxmox client based on configurations."""
    if settings.MOCK_MODE:
        return MockProxmoxClient()
    return ProxmoxVEClient()
