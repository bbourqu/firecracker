#!/usr/bin/env python3
"""
VM Manager for Firecracker OpenAI Code Generator

Provides centralized virtual machine lifecycle management for Firecracker microVMs.
Handles VM creation, configuration, process management, and shared disk operations.

Features:
- VM configuration generation with kernel, rootfs, and networking
- Shared EXT4 disk creation for host-VM communication
- VM process lifecycle management (start, monitor, stop)
- Graceful shutdown and resource cleanup
- Health checks and monitoring capabilities

Dependencies:
- firecracker: AWS Firecracker binary for microVM management
- subprocess: System process management
- pathlib: Modern path handling
- tempfile: Temporary file operations
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Any
import signal
import psutil

from loguru import logger
from omegaconf import DictConfig
from validation import validate_mcp_request
from launcher import start_launcher, stop_launcher
import firecracker_client
from tools.guest_tools import create_guest_tar, create_init_overlay
from provider_client import post_with_retries
from utils.provider_resolver import resolve_provider_url


class VMInstance:
    """Represents a Firecracker VM instance with its configuration and state.
    
    Attributes:
        vm_id (str): Unique identifier for the VM
        config (Dict[str, Any]): VM configuration dictionary
        process (subprocess.Popen): VM process handle
        socket_path (Path): Path to Firecracker API socket
        shared_disk_path (Path): Path to shared communication disk
        tap_name (str): TAP network interface name
    """
    
    def __init__(self, vm_id: str):
        self.vm_id = vm_id
        self.config: Optional[Dict[str, Any]] = None
        self.process: Optional[subprocess.Popen] = None
        self.socket_path: Optional[Path] = None
        self.shared_disk_path: Optional[Path] = None
        self.tap_name: Optional[str] = None


class VMManager:
    """Centralized virtual machine lifecycle management for Firecracker microVMs.
    
    Manages the complete lifecycle of Firecracker VMs including configuration generation,
    shared disk creation, process management, and cleanup. Provides a clean interface
    for VM operations while handling all the underlying complexity.
    
    Attributes:
        config (DictConfig): Configuration object with VM settings
        active_vms (Dict[str, VMInstance]): Currently active VM instances
        
    Example:
        vm_manager = VMManager(config)
        vm_instance = vm_manager.create_vm("abc123", task_data)
        vm_manager.start_vm(vm_instance)
        vm_manager.stop_vm(vm_instance)
    """
    
    def __init__(self, config: DictConfig):
        """Initialize the VM manager with configuration.
        
        Args:
            config (DictConfig): Configuration object with VM and path settings
        """
        self.config = config
        self.active_vms: Dict[str, VMInstance] = {}
        
        # Ensure required directories exist
        Path(config.paths.shared).mkdir(exist_ok=True)
        Path(config.paths.results).mkdir(exist_ok=True)
        
        logger.info("VM Manager initialized", 
                    memory_mb=config.vm.memory_mb,
                    vcpus=config.vm.vcpus,
                    ubuntu_images=str(config.paths.ubuntu_images))
    
    def create_vm(self, vm_id: str, task_data: Optional[Dict[str, Any]] = None) -> VMInstance:
        """Create a new VM instance with complete configuration.
        
        Generates VM configuration, creates shared disk, and prepares all
        resources needed for VM launch. Does not start the VM process.
        
        Args:
            vm_id (str): Unique identifier for the VM instance
            task_data (Dict[str, Any], optional): Task data to pre-load into shared disk
            
        Returns:
            VMInstance: Configured VM instance ready for launch
            
        Raises:
            subprocess.CalledProcessError: If shared disk creation fails
            FileNotFoundError: If required VM image files are missing
            
        Example:
            vm_instance = vm_manager.create_vm("abc123", {
                "task_id": "xyz789", 
                "description": "Create Python hello world"
            })
        """
        logger.info("Creating VM instance", vm_id=vm_id)

        # If task_data present, validate shape early
        if task_data:
            try:
                validate_mcp_request(task_data)
            except Exception as e:
                logger.error("Invalid task_data provided: {}", str(e))
                raise

            # If caller requested a provider invocation, call provider endpoint
            provider = task_data.get('provider')
            if provider:
                # Resolve provider URL using resolver utility
                provider_url = resolve_provider_url(provider, self.config)
                try:
                    prompt = task_data.get('prompt')
                    model = task_data.get('model')
                    # Use provider dispatcher for provider-specific logic
                    from providers import call_provider

                    provider_resp = call_provider(provider, provider_url, model, prompt)
                except Exception as e:
                    logger.warning("Provider call failed: %s", str(e))
                    provider_resp = {"error": str(e)}
                # Record provider response for downstream use
                if not task_data.get('env_overrides'):
                    task_data['env_overrides'] = {}
                task_data['provider_response'] = provider_resp

        
        # Create VM instance object
        vm_instance = VMInstance(vm_id)
        # attach provider_response if present in task_data
        if task_data and 'provider_response' in task_data:
            vm_instance.provider_response = task_data['provider_response']
        vm_instance.tap_name = f"tap{vm_id}"
        vm_instance.socket_path = Path(f"/tmp/firecracker-{vm_id}.socket")
        
        # Create shared disk for communication
        vm_instance.shared_disk_path = self.create_shared_disk(vm_id, task_data)
        
        # Generate VM configuration
        vm_instance.config = self._generate_vm_config(vm_instance)
        # Prepare guest artifacts: guest.tar.gz and init overlay image in dry-run
        results_dir = Path(self.config.paths.results) / vm_id
        results_dir.mkdir(parents=True, exist_ok=True)
        try:
            guest_tar = results_dir / "guest.tar.gz"
            # collect local .specify/scripts for now
            srcs = [Path('.specify/scripts')]
            create_guest_tar(vm_id, srcs, guest_tar)

            init_img = results_dir / "init-overlay.img"
            # create real init overlay only when explicitly enabled in config
            use_real_init = False
            try:
                use_real_init = bool(self.config.vm.get('use_real_init', False))
            except Exception:
                use_real_init = False

            create_init_overlay(vm_id, init_img, dry_run=not use_real_init)

            # Record artefact refs in the vm instance for later use
            vm_instance.shared_disk_path = guest_tar
            vm_instance.config["init_img"] = str(init_img)

        except Exception:
            logger.exception("Failed to prepare guest artifacts for vm %s", vm_id)

        # Write initial manifest to results/<vm_id>/manifest.json
        try:
            self._write_manifest(vm_instance, state="pending")
        except Exception:
            logger.exception("Failed to write initial manifest for vm %s", vm_id)
        
        # Register the VM instance
        self.active_vms[vm_id] = vm_instance
        
        logger.success("VM instance created", 
                      vm_id=vm_id,
                      shared_disk=str(vm_instance.shared_disk_path),
                      tap_name=vm_instance.tap_name)
        
        return vm_instance

    def _write_manifest(self, vm_instance: VMInstance, state: str = "pending") -> None:
        """Write the VM manifest JSON to the results directory for this VM."""
        results_dir = Path(self.config.paths.results) / vm_instance.vm_id
        results_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "vm_id": vm_instance.vm_id,
            "image": Path(self.config.paths.ubuntu_images).name,
            "memory_mb": self.config.vm.memory_mb,
            "vcpus": self.config.vm.vcpus,
            "network_mode": "slirp",
            "created_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            "state": state,
        }
        # include provider response metadata when available
        try:
            prov = None
            if vm_instance.config and isinstance(vm_instance.config, dict):
                prov = vm_instance.config.get('provider_response')
            if not prov and hasattr(vm_instance, 'provider_response'):
                prov = getattr(vm_instance, 'provider_response')
            if prov:
                manifest['provider_response'] = prov
        except Exception:
            pass
        manifest_path = results_dir / "manifest.json.tmp"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        # atomic rename
        manifest_path.rename(results_dir / "manifest.json")
    
    def _generate_vm_config(self, vm_instance: VMInstance) -> Dict[str, Any]:
        """Generate complete Firecracker VM configuration.
        
        Args:
            vm_instance (VMInstance): VM instance to configure
            
        Returns:
            Dict[str, Any]: Complete VM configuration for Firecracker
        """
        config = {
            "boot-source": {
                "kernel_image_path": str(self.config.paths.ubuntu_images / "vmlinux.bin"),
                "boot_args": (
                    f"console=ttyS0 reboot=k panic=1 pci=off init=/ssl_agent.sh "
                    f"VM_IP=172.50.0.2 GATEWAY_IP=172.50.0.1"
                )
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": str(self.config.paths.ubuntu_images / "ubuntu-rootfs.ext4"),
                    "is_root_device": True,
                    "is_read_only": False
                },
                {
                    "drive_id": "shared",
                    "path_on_host": str(vm_instance.shared_disk_path),
                    "is_root_device": False,
                    "is_read_only": False
                }
            ],
            "network-interfaces": [
                {
                    "iface_id": "eth0",
                    "guest_mac": "AA:FC:00:00:00:01",
                    "host_dev_name": vm_instance.tap_name
                }
            ],
            "machine-config": {
                "vcpu_count": self.config.vm.vcpus,
                "mem_size_mib": self.config.vm.memory_mb,
                "smt": False
            }
        }
        
        return config
    
    def create_shared_disk(self, vm_id: str, task_data: Optional[Dict[str, Any]] = None) -> Path:
        """Create EXT4 shared disk for host-VM task communication.
        
        Creates a temporary EXT4 filesystem that serves as the communication
        channel between host and VM. Tasks are placed in tasks/ directory
        and results are returned in results/ directory.
        
        Args:
            vm_id (str): Unique VM identifier for disk naming
            task_data (Dict[str, Any], optional): Task data to pre-load into disk
            
        Returns:
            Path: Path to the created shared disk image
            
        Raises:
            subprocess.CalledProcessError: If disk creation or mounting fails
        """
        shared_disk_path = Path(f"/tmp/shared-{vm_id}.ext4")
        
        logger.info("Creating shared disk", path=str(shared_disk_path), vm_id=vm_id)
        
        # Create a small disk image (50MB)
        subprocess.run([
            "dd", "if=/dev/zero", f"of={shared_disk_path}", "bs=1M", "count=50"
        ], check=True, capture_output=True)
        
        # Format it as ext4
        subprocess.run([
            "mkfs.ext4", "-F", str(shared_disk_path)
        ], check=True, capture_output=True)
        
        # Mount it temporarily to copy shared data
        mount_point = Path(f"/tmp/shared-mount-{vm_id}")
        mount_point.mkdir(exist_ok=True)
        
        subprocess.run([
            "sudo", "mount", str(shared_disk_path), str(mount_point)
        ], check=True)
        
        try:
            # Create directories with sudo
            subprocess.run([
                "sudo", "mkdir", "-p", 
                str(mount_point / "tasks"), 
                str(mount_point / "results")
            ], check=True)
            
            # Copy existing tasks if any
            tasks_dir = Path(self.config.paths.shared) / "tasks"
            if tasks_dir.exists():
                for task_file in tasks_dir.glob("*.json"):
                    subprocess.run([
                        "sudo", "cp", str(task_file), 
                        str(mount_point / "tasks" / task_file.name)
                    ], check=True)
            
            # If we have task data to pre-load, add it now
            if task_data:
                self._preload_task_data(mount_point, task_data, vm_id)
            
            # Set permissions for VM access
            subprocess.run([
                "sudo", "chmod", "-R", "777", str(mount_point)
            ], check=True)
            
            logger.success("Shared disk created and initialized", 
                          path=str(shared_disk_path), vm_id=vm_id)
            
        finally:
            # Always unmount
            subprocess.run([
                "sudo", "umount", str(mount_point)
            ], check=True)
            mount_point.rmdir()
        
        return shared_disk_path
    
    def _preload_task_data(self, mount_point: Path, task_data: Dict[str, Any], vm_id: str):
        """Pre-load task data into shared disk.
        
        Args:
            mount_point (Path): Mounted shared disk path
            task_data (Dict[str, Any]): Task data to load
            vm_id (str): VM identifier for logging
        """
        task_file_path = mount_point / "tasks" / f"{task_data['task_id']}.json"
        
        # Create a temporary file first, then copy with sudo
        temp_file = Path(f"/tmp/task-{task_data['task_id']}.json")
        with open(temp_file, 'w') as f:
            json.dump(task_data, f, indent=2)
        
        # Copy to mounted filesystem with sudo
        subprocess.run([
            "sudo", "cp", str(temp_file), str(task_file_path)
        ], check=True)
        
        # Clean up temp file
        temp_file.unlink()
        
        subprocess.run([
            "sudo", "chown", "root:root", str(task_file_path)
        ], check=True)
        
        logger.debug("Pre-loaded task into shared disk", 
                    task_id=task_data['task_id'], vm_id=vm_id)
    
    def start_vm(self, vm_instance: VMInstance, openai_api_key: Optional[str] = None) -> subprocess.Popen:
        """Start Firecracker VM with complete configuration.
        
        Launches the Firecracker process with the VM configuration and
        waits for it to boot successfully. Injects OpenAI API key if provided.
        
        Args:
            vm_instance (VMInstance): VM instance to start
            openai_api_key (str, optional): OpenAI API key to inject via kernel args
            
        Returns:
            subprocess.Popen: Running VM process
            
        Raises:
            subprocess.CalledProcessError: If VM fails to start
            TimeoutError: If VM boot timeout is exceeded
            
        Example:
            process = vm_manager.start_vm(vm_instance, openai_api_key="sk-...")
        """
        logger.info("Starting VM", 
                   vm_id=vm_instance.vm_id,
                   memory_mb=self.config.vm.memory_mb,
                   vcpus=self.config.vm.vcpus)
        
        # Inject OpenAI API key into kernel boot args if provided
        if openai_api_key:
            boot_args = vm_instance.config["boot-source"]["boot_args"]
            vm_instance.config["boot-source"]["boot_args"] = f"{boot_args} OPENAI_API_KEY={openai_api_key}"

        # Write VM configuration to file
        config_path = Path(f"/tmp/vm-config-{vm_instance.vm_id}.json")
        with open(config_path, 'w') as f:
            json.dump(vm_instance.config, f, indent=2)

        # Remove existing socket if present
        if vm_instance.socket_path and vm_instance.socket_path.exists():
            vm_instance.socket_path.unlink()

        # Start launcher and capture logs under results
        try:
            proc, results_dir = start_launcher(vm_instance.vm_id, str(config_path), self.config.paths.results,
                                               use_jailer=self.config.vm.get('use_jailer', False),
                                               extra_args=[str(vm_instance.config['boot-source']['kernel_image_path']),
                                                           str(vm_instance.config['drives'][0]['path_on_host'])]
                                               )
            vm_instance.process = proc

            # Update manifest to running
            self._write_manifest(vm_instance, state="running")

            # Perform control-plane calls to configure the microVM
            sock = str(vm_instance.socket_path)
            firecracker_client.put_json(sock, "/boot-source", vm_instance.config["boot-source"])
            firecracker_client.put_json(sock, "/machine-config", vm_instance.config["machine-config"])

            logger.success("VM started successfully",
                          vm_id=vm_instance.vm_id,
                          pid=vm_instance.process.pid if vm_instance.process else None,
                          socket=str(vm_instance.socket_path))

        except Exception as e:
            logger.error("Failed to start VM %s: %s", vm_instance.vm_id, str(e))
            # mark manifest failed
            try:
                self._write_manifest(vm_instance, state="failed")
            except Exception:
                logger.exception("Failed writing failed state for %s", vm_instance.vm_id)
            raise

        return vm_instance.process
    
    def stop_vm(self, vm_instance: VMInstance) -> None:
        """Stop Firecracker VM and clean up all resources.
        
        Gracefully terminates the VM process, cleans up temporary files,
        and removes the VM from active instances tracking.
        
        Args:
            vm_instance (VMInstance): VM instance to stop
            
        Example:
            vm_manager.stop_vm(vm_instance)
        """
        logger.info("Stopping VM", vm_id=vm_instance.vm_id)
        
        # Terminate VM process if running
        if vm_instance.process and vm_instance.process.poll() is None:
            try:
                # Try graceful termination first
                vm_instance.process.terminate()
                
                # Wait for graceful shutdown
                try:
                    vm_instance.process.wait(timeout=self.config.vm.shutdown_timeout)
                except subprocess.TimeoutExpired:
                    logger.warning("VM graceful shutdown timeout, forcing kill", 
                                 vm_id=vm_instance.vm_id)
                    vm_instance.process.kill()
                    vm_instance.process.wait()
                
                logger.debug("VM process terminated", 
                           vm_id=vm_instance.vm_id,
                           pid=vm_instance.process.pid)
                
            except ProcessLookupError:
                logger.debug("VM process already terminated", vm_id=vm_instance.vm_id)
        
        # Clean up temporary files
        self._cleanup_vm_files(vm_instance)
        
        # Remove from active instances
        if vm_instance.vm_id in self.active_vms:
            del self.active_vms[vm_instance.vm_id]
        
        logger.success("VM stopped and cleaned up", vm_id=vm_instance.vm_id)
    
    def _cleanup_vm_files(self, vm_instance: VMInstance):
        """Clean up temporary files for a VM instance.
        
        Args:
            vm_instance (VMInstance): VM instance to clean up
        """
        # Clean up socket file
        if vm_instance.socket_path and vm_instance.socket_path.exists():
            try:
                vm_instance.socket_path.unlink()
                logger.debug("Removed socket file", path=str(vm_instance.socket_path))
            except OSError as e:
                logger.warning("Failed to remove socket file", 
                             path=str(vm_instance.socket_path), error=str(e))
        
        # Clean up shared disk
        if vm_instance.shared_disk_path and vm_instance.shared_disk_path.exists():
            try:
                vm_instance.shared_disk_path.unlink()
                logger.debug("Removed shared disk", path=str(vm_instance.shared_disk_path))
            except OSError as e:
                logger.warning("Failed to remove shared disk", 
                             path=str(vm_instance.shared_disk_path), error=str(e))
        
        # Clean up config file
        config_path = Path(f"/tmp/vm-config-{vm_instance.vm_id}.json")
        if config_path.exists():
            try:
                config_path.unlink()
                logger.debug("Removed config file", path=str(config_path))
            except OSError as e:
                logger.warning("Failed to remove config file", 
                             path=str(config_path), error=str(e))
    
    def get_vm_status(self, vm_instance: VMInstance) -> Dict[str, Any]:
        """Get current status of a VM instance.
        
        Args:
            vm_instance (VMInstance): VM instance to check
            
        Returns:
            Dict[str, Any]: VM status information
        """
        status = {
            "vm_id": vm_instance.vm_id,
            "running": False,
            "pid": None,
            "memory_mb": self.config.vm.memory_mb,
            "vcpus": self.config.vm.vcpus
        }
        
        if vm_instance.process:
            status["pid"] = vm_instance.process.pid
            status["running"] = vm_instance.process.poll() is None
            
            # Get memory usage if process is running
            if status["running"]:
                try:
                    process = psutil.Process(vm_instance.process.pid)
                    status["memory_usage_mb"] = process.memory_info().rss / 1024 / 1024
                    status["cpu_percent"] = process.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    status["running"] = False
        
        return status
    
    def mount_shared_disk(self, vm_id: str) -> Path:
        """Mount shared disk for result retrieval.
        
        Args:
            vm_id (str): VM identifier
            
        Returns:
            Path: Mount point path
            
        Raises:
            subprocess.CalledProcessError: If mounting fails
        """
        shared_disk_path = Path(f"/tmp/shared-{vm_id}.ext4")
        mount_point = Path(f"/tmp/shared-mount-{vm_id}")
        
        if not shared_disk_path.exists():
            raise FileNotFoundError(f"Shared disk not found: {shared_disk_path}")
        
        mount_point.mkdir(exist_ok=True)
        
        subprocess.run([
            "sudo", "mount", str(shared_disk_path), str(mount_point)
        ], check=True)
        
        logger.debug("Shared disk mounted", 
                    disk=str(shared_disk_path), 
                    mount_point=str(mount_point))
        
        return mount_point
    
    def unmount_shared_disk(self, vm_id: str) -> None:
        """Unmount shared disk.
        
        Args:
            vm_id (str): VM identifier
        """
        mount_point = Path(f"/tmp/shared-mount-{vm_id}")
        
        if mount_point.exists():
            try:
                subprocess.run([
                    "sudo", "umount", str(mount_point)
                ], check=True)
                mount_point.rmdir()
                logger.debug("Shared disk unmounted", mount_point=str(mount_point))
            except subprocess.CalledProcessError as e:
                logger.warning("Failed to unmount shared disk", 
                             mount_point=str(mount_point), error=str(e))
    
    def cleanup_all_vms(self) -> None:
        """Clean up all active VM instances.
        
        Stops all running VMs and cleans up their resources.
        Used for graceful shutdown of the entire system.
        """
        logger.info("Cleaning up all VMs", count=len(self.active_vms))
        
        for vm_instance in list(self.active_vms.values()):
            self.stop_vm(vm_instance)
        
        logger.success("All VMs cleaned up", count=len(self.active_vms))