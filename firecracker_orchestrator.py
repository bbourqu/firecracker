#!/usr/bin/env python3
"""
Firecracker OpenAI Code Generator

A secure, isolated code generation system using AWS Firecracker microVMs and OpenAI API integration.
Each code generation task runs in a completely isolated virtual machine with automatic cleanup.

Features:
- Secure VM isolation for each task
- Real OpenAI API integration with SSL/TLS support
- Multi-language code generation (Python, JavaScript, Go, Bash)
- Automatic results storage with unique naming
- Complete resource cleanup after each task
- Configurable logging levels

Dependencies:
- AWS Firecracker v1.10.0+
- Ubuntu 22.04 LTS VM images
- Python 3.7+
- Linux host with root privileges for networking

Example Usage:
    # Basic code generation
    python3 firecracker_orchestrator.py run "Create a Python fibonacci function"
    
    # Interactive mode
    python3 firecracker_orchestrator.py interactive
    
    # Debug mode
    python3 firecracker_orchestrator.py --debug run "Write a bash script"
"""

import json
import os
import sys
import time
import subprocess
import tempfile
import uuid
from pathlib import Path
import threading
import signal
from typing import Optional

# Loguru for enhanced logging
from loguru import logger

# Hydra and OmegaConf for configuration management
import hydra
from omegaconf import DictConfig, OmegaConf
from hydra import compose, initialize

# Import our configuration schema
from config.schema import FirecrackerOrchestratorConfig

# Import from modular components
from logging_manager import setup_logging
from config_manager import ConfigManager
from vm_manager import VMManager
from network_manager import NetworkManager


class FirecrackerOrchestrator:
    """
    Orchestrates Firecracker microVM instances for secure OpenAI code generation.
    
    This class manages the complete lifecycle of isolated microVMs that execute
    code generation tasks using the OpenAI API. Each task runs in a separate VM
    with complete network isolation and automatic cleanup.
    
    Attributes:
        config (OrchestratorConfig): Configuration and logging settings
        openai_api_key (str): OpenAI API key for code generation
        vm_process (subprocess.Popen): Currently running VM process
        vm_socket (str): Path to Firecracker API socket
        
    Example:
        orchestrator = FirecrackerOrchestrator(config=config, openai_api_key="sk-...")
        result = orchestrator.run_experiment("Create a Python hello world program")
        print(result['generated_code'])
    """
    
    def __init__(self, config: DictConfig, openai_api_key: Optional[str] = None):
        """Initialize the orchestrator with Hydra configuration and API credentials.
        
        Args:
            config (DictConfig): Hydra configuration object with all settings
            openai_api_key (str, optional): OpenAI API key. If not provided, reads from
                                          OPENAI_API_KEY environment variable.
                                          
        Raises:
            ValueError: If no OpenAI API key is provided via parameter or environment
        """
        self.config = config
        
        # API key validation
        self.openai_api_key = openai_api_key or os.environ.get('OPENAI_API_KEY')
        if not self.openai_api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY environment variable or pass as parameter.")
        
        # Directory setup - convert config paths to Path objects
        self.tasks_dir = Path(config.paths.shared) / "tasks"
        self.results_dir = Path(config.paths.shared) / "results"
        
        # Create required directories
        Path(config.paths.shared).mkdir(exist_ok=True)
        self.tasks_dir.mkdir(exist_ok=True)
        self.results_dir.mkdir(exist_ok=True)
        Path(config.paths.results).mkdir(exist_ok=True)
        
        # Initialize modular components
        self.vm_manager = VMManager(config)
        self.network_manager = NetworkManager(config)
        
        # VM state (for backward compatibility)
        self.vm_process = None
        self.vm_socket = None
        
        logger.info("Firecracker orchestrator initialized with modular components")
        
    def create_vm_config(self, vm_id, task_data=None):
        """Create Firecracker VM configuration with networking and shared disk.
        
        Generates a complete VM configuration including kernel, rootfs, networking,
        and shared disk for task communication. The VM is configured with Ubuntu
        22.04 LTS and includes OpenAI API key injection via kernel command line.
        
        Args:
            vm_id (str): Unique identifier for the VM instance
            task_data (dict, optional): Task data to pre-load into shared disk
            
        Returns:
            dict: Complete Firecracker VM configuration ready for launch
            
        Example:
            config = orchestrator.create_vm_config("abc123", {"task_id": "xyz", ...})
        """
        # Create a shared disk image for host-VM communication
        shared_disk = self.create_shared_disk(vm_id, task_data)
        tap_name = f"tap{vm_id}"
        
        config = {
            "boot-source": {
                "kernel_image_path": str(Path(self.config.paths.ubuntu_images) / "vmlinux.bin"),
                "boot_args": f"console=ttyS0 reboot=k panic=1 pci=off init=/ssl_agent.sh OPENAI_API_KEY={self.openai_api_key} VM_IP=172.50.0.2 GATEWAY_IP=172.50.0.1"
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": str(Path(self.config.paths.ubuntu_images) / "ubuntu-rootfs.ext4"),
                    "is_root_device": True,
                    "is_read_only": False
                },
                {
                    "drive_id": "shared",
                    "path_on_host": str(shared_disk),
                    "is_root_device": False,
                    "is_read_only": False
                }
            ],
            "network-interfaces": [
                {
                    "iface_id": "eth0",
                    "guest_mac": "AA:FC:00:00:00:01",
                    "host_dev_name": tap_name
                }
            ],
            "machine-config": {
                "vcpu_count": self.config.vm.vcpus,
                "mem_size_mib": self.config.vm.memory_mb,
                "smt": False
            }
        }
        return config
    
    def create_shared_disk(self, vm_id, task_data=None):
        """Create EXT4 shared disk for host-VM task communication.
        
        Creates a temporary EXT4 filesystem that serves as the communication
        channel between host and VM. Tasks are placed in tasks/ directory
        and results are returned in results/ directory.
        
        Args:
            vm_id (str): Unique VM identifier for disk naming
            task_data (dict, optional): Task data to pre-load into disk
            
        Returns:
            Path: Path to the created shared disk image
            
        Raises:
            subprocess.CalledProcessError: If disk creation or mounting fails
        """
        shared_disk_path = Path(f"/tmp/shared-{vm_id}.ext4")
        
        logger.info("Creating shared disk", path=shared_disk_path, vm_id=vm_id)
        
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
                "sudo", "mkdir", "-p", str(mount_point / "tasks"), str(mount_point / "results")
            ], check=True)
            
            # Copy existing tasks if any
            for task_file in self.tasks_dir.glob("*.json"):
                subprocess.run([
                    "sudo", "cp", str(task_file), str(mount_point / "tasks" / task_file.name)
                ], check=True)
            
            # If we have task data to pre-load, add it now
            if task_data:
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
            
            # Set permissions for VM access
            subprocess.run([
                "sudo", "chmod", "-R", "777", str(mount_point)
            ], check=True)
            
            logger.success("Shared disk created and initialized", 
                          path=shared_disk_path, vm_id=vm_id)
            
        finally:
            subprocess.run([
                "sudo", "umount", str(mount_point)
            ], check=True)
            mount_point.rmdir()
        
        return shared_disk_path
    
    def setup_networking(self, vm_id):
        """Set up TAP interface and NAT routing for VM internet access.
        
        Creates a TAP network interface for the VM with proper IP configuration,
        sets up NAT routing through the host's default interface, and configures
        iptables rules for internet connectivity.
        
        Network Configuration:
        - TAP interface: tap{vm_id} with IP 172.50.0.1/24
        - VM gets IP: 172.50.0.2/24 via DHCP
        - NAT routing through host's default interface
        - DNS: 8.8.8.8 (configured in VM)
        
        Args:
            vm_id (str): Unique VM identifier for interface naming
            
        Returns:
            str: Name of created TAP interface, or None if setup failed
            
        Raises:
            subprocess.CalledProcessError: If network setup commands fail
        """
        tap_name = f"tap{vm_id}"
        
        logger.debug("Setting up network interface", tap_name=tap_name, vm_id=vm_id)
        
        try:
            # Create TAP interface
            subprocess.run([
                "sudo", "ip", "tuntap", "add", "dev", tap_name, "mode", "tap"
            ], check=True)
            
            # Assign IP address to TAP interface (host side)  
            subprocess.run([
                "sudo", "ip", "addr", "add", "172.50.0.1/24", "dev", tap_name
            ], check=True)
            
            # Use standard MTU for better compatibility
            subprocess.run([
                "sudo", "ip", "link", "set", "dev", tap_name, "mtu", "1500"
            ], check=True)
            
            # Bring up the interface
            subprocess.run([
                "sudo", "ip", "link", "set", "dev", tap_name, "up"
            ], check=True)
            
            # Enable IP forwarding
            subprocess.run([
                "sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"
            ], check=True)
            
            # Set up NAT for internet access by finding default route interface
            try:
                result = subprocess.run([
                    "ip", "route", "show", "default"
                ], capture_output=True, text=True, check=True)
                
                # Extract interface name from default route
                default_iface = None
                for line in result.stdout.split('\n'):
                    if 'default' in line and 'dev' in line:
                        parts = line.split()
                        dev_index = parts.index('dev')
                        if dev_index + 1 < len(parts):
                            default_iface = parts[dev_index + 1]
                            break
                
                if default_iface:
                    # Configure iptables NAT rules for internet access
                    subprocess.run([
                        "sudo", "iptables", "-t", "nat", "-A", "POSTROUTING", 
                        "-s", "172.50.0.0/24", "-o", default_iface, "-j", "MASQUERADE"
                    ], check=True)
                    
                    subprocess.run([
                        "sudo", "iptables", "-A", "FORWARD", "-i", tap_name, 
                        "-o", default_iface, "-j", "ACCEPT"
                    ], check=True)
                    
                    subprocess.run([
                        "sudo", "iptables", "-A", "FORWARD", "-i", default_iface, 
                        "-o", tap_name, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"
                    ], check=True)
                    
                    logger.success("NAT configured", 
                                  tap_interface=tap_name, 
                                  default_interface=default_iface, 
                                  vm_id=vm_id)
                else:
                    logger.warning("Could not determine default interface for NAT", 
                                 tap_name=tap_name, vm_id=vm_id)
                    
            except subprocess.CalledProcessError as e:
                logger.warning("Failed to set up NAT", error=str(e), 
                             tap_name=tap_name, vm_id=vm_id)
            
            return tap_name
            
        except subprocess.CalledProcessError as e:
            logger.error("Failed to set up networking", error=str(e), vm_id=vm_id)
            return None
    
    def cleanup_networking(self, tap_name):
        """Clean up TAP interface and associated iptables NAT rules.
        
        Removes the TAP interface and all associated iptables rules that were
        created for VM networking. Safely handles cases where rules or interface
        may have already been removed.
        
        Args:
            tap_name (str): Name of the TAP interface to remove
        """
        try:
            # Get the default route interface for cleanup
            try:
                result = subprocess.run([
                    "ip", "route", "show", "default"
                ], capture_output=True, text=True, check=True)
                
                default_iface = None
                for line in result.stdout.split('\n'):
                    if 'default' in line and 'dev' in line:
                        parts = line.split()
                        dev_index = parts.index('dev')
                        if dev_index + 1 < len(parts):
                            default_iface = parts[dev_index + 1]
                            break
                
                if default_iface:
                    # Remove iptables rules (ignore errors if rules don't exist)
                    subprocess.run([
                        "sudo", "iptables", "-t", "nat", "-D", "POSTROUTING", 
                        "-s", "172.50.0.0/24", "-o", default_iface, "-j", "MASQUERADE"
                    ], check=False)
                    
                    subprocess.run([
                        "sudo", "iptables", "-D", "FORWARD", "-i", tap_name, 
                        "-o", default_iface, "-j", "ACCEPT"
                    ], check=False)
                    
                    subprocess.run([
                        "sudo", "iptables", "-D", "FORWARD", "-i", default_iface, 
                        "-o", tap_name, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"
                    ], check=False)
                    
            except subprocess.CalledProcessError:
                pass  # Ignore errors during cleanup
            
            # Delete TAP interface
            subprocess.run([
                "sudo", "ip", "link", "delete", tap_name
            ], check=False)  # Don't fail if already deleted
            
        except Exception as e:
            logger.warning("Failed to cleanup network interface", tap_name=tap_name, error=str(e))
    
    def start_vm(self, vm_id, task_data=None):
        """Start Firecracker VM with complete configuration and networking.
        
        Creates VM configuration, sets up networking, and launches the Firecracker
        process. The VM is configured with Ubuntu 22.04 LTS and includes all
        necessary components for OpenAI API integration.
        
        Args:
            vm_id (str): Unique identifier for this VM instance
            task_data (dict, optional): Task data to pre-load into shared disk
            
        Returns:
            bool: True if VM started successfully, False otherwise
            
        Raises:
            Exception: If networking setup fails
        """
        logger.info("Starting VM", vm_id=vm_id, 
                   memory_mb=self.config.vm.memory_mb, 
                   vcpus=self.config.vm.vcpus)
        
        # Set up networking infrastructure
        tap_name = self.setup_networking(vm_id)
        if not tap_name:
            raise Exception("Failed to set up VM networking")
        
        # Create VM configuration
        config = self.create_vm_config(vm_id, task_data)
        config_file = Path(f"/tmp/vm-config-{vm_id}.json")
        
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        logger.debug("VM config written", config_file=config_file, vm_id=vm_id)
        if self.config.logging.level == "DEBUG":
            logger.debug("VM configuration", vm_id=vm_id, config=config)
        
        # Create socket path
        socket_path = f"/tmp/firecracker-{vm_id}.socket"
        self.vm_socket = socket_path
        
        # Create log files for VM output
        vm_log_file = Path(f"/tmp/vm-{vm_id}.log")
        vm_err_file = Path(f"/tmp/vm-{vm_id}.err")
        
        try:
            # Start Firecracker with output redirection
            with open(vm_log_file, 'w') as log_f, open(vm_err_file, 'w') as err_f:
                self.vm_process = subprocess.Popen([
                    "firecracker",
                    "--api-sock", socket_path,
                    "--config-file", str(config_file)
                ], stdout=log_f, stderr=err_f)
            
            logger.success("Firecracker process started", 
                          vm_id=vm_id, 
                          pid=self.vm_process.pid,
                          socket_path=socket_path)
            logger.debug("VM logging configured", 
                        vm_id=vm_id, 
                        log_file=vm_log_file, 
                        error_file=vm_err_file)
            
            # Wait briefly and verify process is running
            time.sleep(2)
            if self.vm_process.poll() is not None:
                logger.error("Firecracker process exited early", 
                           vm_id=vm_id, 
                           return_code=self.vm_process.returncode)
                with open(vm_err_file, 'r') as f:
                    err_content = f.read()
                    if err_content:
                        logger.error("VM startup error output", 
                                   vm_id=vm_id, 
                                   error_output=err_content)
                return False
            
            logger.success("VM started successfully", 
                         vm_id=vm_id, 
                         memory_mb=self.config.vm.memory_mb,
                         vcpus=self.config.vm.vcpus)
            return True
            
        except Exception as e:
            logger.error("Failed to start VM", vm_id=vm_id, error=str(e))
            self.cleanup_networking(tap_name)
            return False
    
    def stop_vm(self, vm_id):
        """Stop Firecracker VM and clean up all resources.
        
        Gracefully terminates the VM process, cleans up networking,
        and removes temporary files. Uses SIGTERM first, then SIGKILL
        if necessary.
        
        Args:
            vm_id (str): VM identifier for cleanup
        """
        logger.info("Stopping VM", vm_id=vm_id)
        
        if self.vm_process:
            try:
                # Try graceful shutdown first
                self.vm_process.terminate()
                self.vm_process.wait(timeout=10)
                logger.debug("VM shutdown gracefully", vm_id=vm_id)
            except subprocess.TimeoutExpired:
                # Force kill if graceful shutdown fails
                logger.warning("VM did not shut down gracefully, forcing termination", vm_id=vm_id)
                self.vm_process.kill()
                self.vm_process.wait()
            
            self.vm_process = None
        
        # Clean up networking infrastructure
        tap_name = f"tap{vm_id}"
        self.cleanup_networking(tap_name)
        
        # Clean up socket file
        if self.vm_socket and os.path.exists(self.vm_socket):
            os.unlink(self.vm_socket)
        
        logger.success("VM stopped and cleaned up", vm_id=vm_id)
    
    def submit_task(self, instruction, timeout=60, vm_id=None):
        """Submit a task to the VM and wait for results"""
        task_id = str(uuid.uuid4())[:8]
        
        # Create task file
        task_data = {
            "task_id": task_id,
            "description": instruction,
            "timestamp": time.time()
        }
        
        task_file = self.tasks_dir / f"{task_id}.json"
        with open(task_file, 'w') as f:
            json.dump(task_data, f, indent=2)
        
        # Copy task file to VM's shared disk if vm_id is provided
        if vm_id:
            shared_disk_path = Path(f"/tmp/shared-{vm_id}.ext4")
            mount_point = Path(f"/tmp/shared-mount-{vm_id}")
            mount_point.mkdir(exist_ok=True)
            
            try:
                subprocess.run([
                    "sudo", "mount", str(shared_disk_path), str(mount_point)
                ], check=True)
                
                # Copy task file to shared disk
                subprocess.run([
                    "sudo", "cp", str(task_file), str(mount_point / "tasks" / f"{task_id}.json")
                ], check=True)
                
                print(f"Task file copied to VM shared disk")
                
            except subprocess.CalledProcessError as e:
                print(f"Failed to copy task to shared disk: {e}")
            finally:
                subprocess.run([
                    "sudo", "umount", str(mount_point)
                ], check=False)
                mount_point.rmdir()
        
        logger.info("Task submitted", 
                   task_id=task_id, 
                   instruction=instruction,
                   vm_id=vm_id)
        logger.debug("Task file written", 
                    task_id=task_id,
                    task_file=task_file,
                    expected_result=self.results_dir / f'{task_id}_result.json')
        
        # Debug directory contents only in debug mode
        if self.config.logging.level == "DEBUG":
            logger.debug("Directory contents", 
                        tasks=list(self.tasks_dir.glob('*')),
                        results=list(self.results_dir.glob('*')))
        
        # Wait for result (Ubuntu agent creates files as {task_id}.json)
        result_file = self.results_dir / f"{task_id}.json"
        start_time = time.time()
        last_log_time = 0
        
        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time
            
            # Log waiting message every 10 seconds, not every iteration
            if elapsed - last_log_time >= 10:
                logger.info("Waiting for result", elapsed=f"{elapsed:.0f}s")
                if self.config.logging.level == "DEBUG":
                    logger.debug("Current tasks", tasks=list(self.tasks_dir.glob('*')))
                    logger.debug("Current results", results=list(self.results_dir.glob('*')))
                last_log_time = elapsed
            
            if result_file.exists():
                with open(result_file, 'r') as f:
                    result = json.load(f)
                
                logger.info("Result received", elapsed=f"{elapsed:.1f}s")
                
                # Clean up task and result files
                task_file.unlink(missing_ok=True)
                result_file.unlink(missing_ok=True)
                
                return result
            
            time.sleep(1)
        
        # Timeout occurred
        logger.warning("Task timed out", timeout=timeout)
        if self.config.logging.level == "DEBUG":
            logger.debug("Final tasks directory", tasks=list(self.tasks_dir.glob('*')))
            logger.debug("Final results directory", results=list(self.results_dir.glob('*')))
        task_file.unlink(missing_ok=True)
        return {
            "task_id": task_id,
            "error": "Task timed out",
            "status": "timeout"
        }
    
    def save_result_to_file(self, result):
        """Save experiment result to results folder with unique name"""
        if not result or result.get("status") == "timeout":
            return
        
        # Use results directory from configuration
        results_dir = Path(self.config.paths.results)
        results_dir.mkdir(exist_ok=True)
        
        # Get VM ID and task description for filename
        vm_id = result.get("vm_id", "unknown")
        task_desc = result.get("task_description", "unknown_task")
        
        # Create safe filename from task description
        safe_task = "".join(c for c in task_desc if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_task = safe_task.replace(' ', '_')[:50]  # Limit length
        
        # Generate filename with VM ID and task
        filename = f"{vm_id}_{safe_task}.json"
        filepath = results_dir / filename
        
        # Add save info to result
        result_copy = result.copy()
        result_copy['saved_to'] = str(filepath)
        result_copy['saved_at'] = time.time()
        
        # Write result to file
        try:
            with open(filepath, 'w') as f:
                json.dump(result_copy, indent=2, fp=f)
            logger.info("Result saved to file", filepath=str(filepath))
            
            # Also save just the generated code if it exists
            if 'generated_code' in result and result['generated_code']:
                # Determine file extension from code content
                code_content = result['generated_code']
                if '```python' in code_content:
                    code_ext = 'py'
                elif '```javascript' in code_content:
                    code_ext = 'js'
                elif '```go' in code_content:
                    code_ext = 'go'
                elif '```bash' in code_content:
                    code_ext = 'sh'
                else:
                    code_ext = 'txt'
                
                # Extract code from markdown code blocks
                lines = code_content.split('\n')
                code_lines = []
                in_code_block = False
                
                for line in lines:
                    if line.startswith('```'):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block:
                        code_lines.append(line)
                
                if code_lines:
                    code_filename = f"{vm_id}_{safe_task}.{code_ext}"
                    code_filepath = results_dir / code_filename
                    
                    with open(code_filepath, 'w') as f:
                        f.write('\n'.join(code_lines))
                    logger.info("Generated code saved to file", code_filepath=str(code_filepath))
                    
        except Exception as e:
            logger.error("Error saving result", error=str(e))
    
    def run_experiment(self, instruction="Create a hello world Python program"):
        """Run a complete experiment"""
        vm_id = str(uuid.uuid4())[:8]
        task_id = str(uuid.uuid4())[:8]
        
        # Create task data before starting VM
        task_data = {
            "task_id": task_id,
            "description": instruction,
            "timestamp": time.time()
        }
        
        try:
            # Start VM with pre-loaded task
            if not self.start_vm(vm_id, task_data):
                return {"error": "Failed to start VM"}
            
            # Wait for VM to fully boot and agent to start
            print("Waiting for VM to boot and agent to initialize...")
            time.sleep(15)
            
            # Wait for result from pre-loaded task by checking VM's shared disk
            start_time = time.time()
            timeout = 60
            shared_disk_path = Path(f"/tmp/shared-{vm_id}.ext4")
            vm_log_file = Path(f"/tmp/vm-{vm_id}.log")
            
            print(f"Task {task_id} pre-loaded: {instruction}")
            print(f"Monitoring VM shared disk for result...")
            
            # Wait for VM to complete task (check logs for completion message)
            while time.time() - start_time < timeout:
                elapsed = time.time() - start_time
                if elapsed % 10 == 0 or elapsed < 10:  # Print every 10 seconds or first 10 seconds
                    print(f"Waiting for result... ({elapsed:.0f}s elapsed)")
                
                # Check VM log for task completion
                try:
                    with open(vm_log_file, 'r') as f:
                        log_content = f.read()
                        if "Task completed successfully!" in log_content:
                            print(f"Task completion detected in VM log after {elapsed:.1f}s")
                            break
                except FileNotFoundError:
                    pass
                
                time.sleep(2)
            
            # Stop VM to safely access shared disk
            print("Stopping VM to read result...")
            self.stop_vm(vm_id)
            
            # Now safely mount and read result
            mount_point = Path(f"/tmp/shared-mount-{vm_id}")
            mount_point.mkdir(exist_ok=True)
            
            try:
                # Wait a moment to ensure VM is fully stopped
                time.sleep(2)
                
                # Mount shared disk
                subprocess.run([
                    "sudo", "mount", str(shared_disk_path), str(mount_point)
                ], check=True)
                
                result_file_vm = mount_point / "results" / f"{task_id}.json"
                if result_file_vm.exists():
                    # Read result directly from VM disk
                    try:
                        subprocess.run([
                            "sudo", "cat", str(result_file_vm)
                        ], check=True, capture_output=True, text=True)
                        
                        # If cat worked, copy to host
                        result_file_host = self.results_dir / f"{task_id}_result.json"
                        subprocess.run([
                            "sudo", "cp", str(result_file_vm), str(result_file_host)
                        ], check=True)
                        
                        subprocess.run([
                            "sudo", "chown", f"{os.getuid()}:{os.getgid()}", str(result_file_host)
                        ], check=True)
                        
                        with open(result_file_host, 'r') as f:
                            result = json.load(f)
                        
                        # Add vm_id for results folder naming
                        result['vm_id'] = vm_id
                        
                        print(f"Result received after {elapsed:.1f}s")
                        result_file_host.unlink(missing_ok=True)
                        return result
                        
                    except Exception as e:
                        print(f"Error reading result: {e}")
                        return {
                            "task_id": task_id,
                            "vm_id": vm_id,
                            "error": f"Failed to read result: {e}",
                            "status": "error"
                        }
                else:
                    print("Result file not found in VM shared disk")
                    
            except subprocess.CalledProcessError as e:
                print(f"Failed to mount shared disk: {e}")
            finally:
                subprocess.run([
                    "sudo", "umount", str(mount_point)
                ], check=False, capture_output=True)
                try:
                    mount_point.rmdir()
                except:
                    pass
            
            # Timeout
            print(f"Task timed out after {timeout}s")
            return {
                "task_id": task_id,
                "vm_id": vm_id,
                "error": "Task timed out",
                "status": "timeout"
            }
            
        finally:
            # Always clean up VM
            self.stop_vm(vm_id)
    
    def interactive_mode(self):
        """Run in interactive mode for multiple tasks"""
        vm_id = str(uuid.uuid4())[:8]
        
        try:
            # Start VM
            if not self.start_vm(vm_id):
                print("Failed to start VM")
                return
            
            print("VM started. Waiting for initialization...")
            time.sleep(15)
            print("VM ready! Enter tasks (type 'quit' to exit):")
            
            while True:
                try:
                    instruction = input("\nTask: ").strip()
                    if instruction.lower() in ['quit', 'exit', 'q']:
                        break
                    
                    if instruction:
                        result = self.submit_task(instruction)
                        print(f"\nResult:")
                        print(json.dumps(result, indent=2))
                
                except KeyboardInterrupt:
                    break
            
        finally:
            self.stop_vm(vm_id)

@hydra.main(version_base=None, config_path="config", config_name="default")
def main(cfg: DictConfig) -> None:
    """Main entry point with Hydra configuration management.
    
    Args:
        cfg: Hydra configuration loaded from config files
        
    Example usage:
        # Use default config
        python3 firecracker_orchestrator.py run "Create Python code"
        
        # Use different config
        python3 firecracker_orchestrator.py --config-name=development run "Create code"
        
        # Override specific values
        python3 firecracker_orchestrator.py vm.memory_mb=1024 run "Create code"
    """
    try:
        # Setup Loguru logging based on configuration
        setup_logging(cfg)
        
        # Create orchestrator with Hydra configuration
        orchestrator = FirecrackerOrchestrator(config=cfg)
        
        # Get command from Hydra config (we'll need to add this to the config files)
        command = getattr(cfg, 'command', 'run')
        instruction = getattr(cfg, 'instruction', "Create a hello world Python program")
        
        if command == "run":
            result = orchestrator.run_experiment(instruction)
            
            # Save result to results folder
            orchestrator.save_result_to_file(result)
            
            # Output results based on logging level
            if cfg.logging.level in ["DEBUG", "INFO"]:
                print("\nExperiment Result:")
                print(json.dumps(result, indent=2))
            else:
                if result.get('status') == 'completed' and result.get('generated_code'):
                    print("Code generation completed successfully!")
                    print(f"Results saved to: {cfg.paths.results}/{result.get('vm_id', 'unknown')}_*.json")
                else:
                    print(f"Task status: {result.get('status', 'unknown')}")
            
        elif command == "interactive":
            orchestrator.interactive_mode()
            
        else:
            logger.error("Unknown command", command=command)
            sys.exit(1)
    
    except Exception as e:
        logger.error("Application error", error=str(e))
        if cfg.logging.level == "DEBUG":
            # Loguru automatically includes traceback in exception logging
            logger.exception("Full traceback:")
        sys.exit(1)

if __name__ == "__main__":
    main()
