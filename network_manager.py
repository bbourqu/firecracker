#!/usr/bin/env python3
"""
Network Manager for Firecracker OpenAI Code Generator

Provides centralized network infrastructure management for Firecracker microVMs.
Handles TAP interface creation, NAT configuration, and network cleanup operations.

Features:
- TAP interface creation and configuration with proper IP assignments
- NAT routing setup through host's default interface
- iptables rules management for internet connectivity
- Network validation and health checks
- Graceful cleanup with error handling

Dependencies:
- ip: Linux networking tools for interface management
- iptables: Netfilter userspace utilities for NAT configuration
- subprocess: System command execution
- psutil: System and process utilities (optional for monitoring)
"""

import subprocess
from typing import Optional, Dict, Any, List
import re
import ipaddress

from loguru import logger
from omegaconf import DictConfig


class NetworkManager:
    """Centralized network infrastructure management for Firecracker microVMs.
    
    Manages TAP interface creation, NAT configuration, and cleanup for VM networking.
    Provides internet connectivity to VMs through proper routing and iptables rules.
    
    Attributes:
        config (DictConfig): Configuration object with network settings
        active_interfaces (Dict[str, Dict]): Currently active TAP interfaces
        
    Example:
        network_manager = NetworkManager(config)
        tap_name = network_manager.setup_tap_interface("abc123", "172.50.0.0/24")
        network_manager.setup_nat_routing(tap_name)
        network_manager.cleanup_networking("abc123")
    """
    
    def __init__(self, config: DictConfig):
        """Initialize the network manager with configuration.
        
        Args:
            config (DictConfig): Configuration object with network settings
        """
        self.config = config
        self.active_interfaces: Dict[str, Dict[str, Any]] = {}
        
        # Validate network configuration
        self._validate_network_config()
        
        logger.info("Network Manager initialized", 
                    network_cidr=config.vm.network_cidr)
    
    def _validate_network_config(self):
        """Validate network configuration settings."""
        try:
            network = ipaddress.IPv4Network(self.config.vm.network_cidr, strict=False)
            if not network.is_private:
                raise ValueError(f"Network must be private: {self.config.vm.network_cidr}")
        except ipaddress.AddressValueError as e:
            raise ValueError(f"Invalid network CIDR: {e}")
    
    def setup_tap_interface(self, vm_id: str, cidr: Optional[str] = None) -> Optional[str]:
        """Set up TAP interface for VM networking.
        
        Creates a TAP interface with proper IP configuration for VM communication.
        The interface is configured with the first IP in the subnet (gateway).
        
        Args:
            vm_id (str): Unique VM identifier for interface naming
            cidr (str, optional): Network CIDR. Defaults to config value
            
        Returns:
            str: Name of created TAP interface, or None if setup failed
            
        Raises:
            subprocess.CalledProcessError: If interface creation fails
            
        Example:
            tap_name = network_manager.setup_tap_interface("abc123", "172.50.0.0/24")
            # Creates tap interface 'tapabc123' with IP 172.50.0.1/24
        """
        if cidr is None:
            cidr = self.config.vm.network_cidr
        
        tap_name = f"tap{vm_id}"
        
        logger.info("Setting up TAP interface", 
                   tap_name=tap_name, 
                   cidr=cidr, 
                   vm_id=vm_id)
        
        try:
            # Parse network to get gateway IP (first IP in subnet)
            network = ipaddress.IPv4Network(cidr, strict=False)
            gateway_ip = str(network.network_address + 1)
            
            # Create TAP interface
            subprocess.run([
                "sudo", "ip", "tuntap", "add", "dev", tap_name, "mode", "tap"
            ], check=True)
            
            # Assign IP address to TAP interface (host/gateway side)  
            subprocess.run([
                "sudo", "ip", "addr", "add", f"{gateway_ip}/{network.prefixlen}", "dev", tap_name
            ], check=True)
            
            # Use standard MTU for better compatibility
            subprocess.run([
                "sudo", "ip", "link", "set", "dev", tap_name, "mtu", "1500"
            ], check=True)
            
            # Bring up the interface
            subprocess.run([
                "sudo", "ip", "link", "set", "dev", tap_name, "up"
            ], check=True)
            
            # Store interface information
            self.active_interfaces[vm_id] = {
                "tap_name": tap_name,
                "cidr": cidr,
                "gateway_ip": gateway_ip,
                "vm_ip": str(network.network_address + 2)  # Second IP for VM
            }
            
            logger.success("TAP interface created", 
                          tap_name=tap_name,
                          gateway_ip=gateway_ip,
                          vm_id=vm_id)
            
            return tap_name
            
        except subprocess.CalledProcessError as e:
            logger.error("Failed to create TAP interface", 
                        tap_name=tap_name, 
                        error=str(e), 
                        vm_id=vm_id)
            return None
        except ipaddress.AddressValueError as e:
            logger.error("Invalid network CIDR", cidr=cidr, error=str(e))
            return None
    
    def setup_nat_routing(self, tap_name: str) -> bool:
        """Set up NAT routing for VM internet access.
        
        Configures iptables rules and IP forwarding to enable internet connectivity
        for VMs through the host's default network interface.
        
        Args:
            tap_name (str): Name of the TAP interface to configure NAT for
            
        Returns:
            bool: True if NAT setup successful, False otherwise
            
        Example:
            success = network_manager.setup_nat_routing("tapabc123")
        """
        logger.info("Setting up NAT routing", tap_name=tap_name)
        
        try:
            # Enable IP forwarding
            subprocess.run([
                "sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"
            ], check=True)
            
            # Find default route interface
            default_iface = self._get_default_interface()
            if not default_iface:
                logger.warning("Could not determine default interface for NAT", 
                             tap_name=tap_name)
                return False
            
            # Configure iptables NAT rules for internet access
            network = ipaddress.IPv4Network(self.config.vm.network_cidr, strict=False)
            network_cidr = str(network)
            
            # MASQUERADE rule for outbound traffic
            subprocess.run([
                "sudo", "iptables", "-t", "nat", "-A", "POSTROUTING", 
                "-s", network_cidr, "-o", default_iface, "-j", "MASQUERADE"
            ], check=True)
            
            # FORWARD rules for bidirectional traffic
            subprocess.run([
                "sudo", "iptables", "-A", "FORWARD", "-i", tap_name, 
                "-o", default_iface, "-j", "ACCEPT"
            ], check=True)
            
            subprocess.run([
                "sudo", "iptables", "-A", "FORWARD", "-i", default_iface, 
                "-o", tap_name, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"
            ], check=True)
            
            logger.success("NAT routing configured", 
                          tap_interface=tap_name, 
                          default_interface=default_iface,
                          network_cidr=network_cidr)
            
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error("Failed to set up NAT routing", 
                        tap_name=tap_name, 
                        error=str(e))
            return False
    
    def _get_default_interface(self) -> Optional[str]:
        """Get the default network interface for NAT routing.
        
        Returns:
            str: Default interface name, or None if not found
        """
        try:
            result = subprocess.run([
                "ip", "route", "show", "default"
            ], capture_output=True, text=True, check=True)
            
            # Parse output to find interface
            for line in result.stdout.split('\n'):
                if 'default' in line and 'dev' in line:
                    parts = line.split()
                    try:
                        dev_index = parts.index('dev')
                        if dev_index + 1 < len(parts):
                            return parts[dev_index + 1]
                    except ValueError:
                        continue
            
            return None
            
        except subprocess.CalledProcessError:
            return None
    
    def cleanup_networking(self, vm_id: str) -> None:
        """Clean up TAP interface and associated iptables NAT rules.
        
        Removes the TAP interface and all associated iptables rules that were
        created for VM networking. Safely handles cases where rules or interface
        may have already been removed.
        
        Args:
            vm_id (str): VM identifier whose networking should be cleaned up
        """
        if vm_id not in self.active_interfaces:
            logger.debug("No active interface found for cleanup", vm_id=vm_id)
            return
        
        interface_info = self.active_interfaces[vm_id]
        tap_name = interface_info["tap_name"]
        
        logger.info("Cleaning up networking", tap_name=tap_name, vm_id=vm_id)
        
        try:
            # Clean up iptables rules
            self._cleanup_iptables_rules(interface_info)
            
            # Delete TAP interface
            subprocess.run([
                "sudo", "ip", "link", "delete", tap_name
            ], check=False)  # Don't fail if already deleted
            
            # Remove from active interfaces
            del self.active_interfaces[vm_id]
            
            logger.success("Network cleanup completed", 
                          tap_name=tap_name, 
                          vm_id=vm_id)
            
        except Exception as e:
            logger.warning("Failed to cleanup network interface", 
                          tap_name=tap_name, 
                          vm_id=vm_id, 
                          error=str(e))
    
    def _cleanup_iptables_rules(self, interface_info: Dict[str, Any]) -> None:
        """Clean up iptables rules for a specific interface.
        
        Args:
            interface_info (Dict[str, Any]): Interface information dict
        """
        tap_name = interface_info["tap_name"]
        default_iface = self._get_default_interface()
        
        if not default_iface:
            logger.debug("Could not determine default interface for cleanup", 
                        tap_name=tap_name)
            return
        
        # Parse network CIDR from interface info
        network = ipaddress.IPv4Network(interface_info["cidr"], strict=False)
        network_cidr = str(network)
        
        # Remove iptables rules (ignore errors if rules don't exist)
        rules_to_remove = [
            ["sudo", "iptables", "-t", "nat", "-D", "POSTROUTING", 
             "-s", network_cidr, "-o", default_iface, "-j", "MASQUERADE"],
            ["sudo", "iptables", "-D", "FORWARD", "-i", tap_name, 
             "-o", default_iface, "-j", "ACCEPT"],
            ["sudo", "iptables", "-D", "FORWARD", "-i", default_iface, 
             "-o", tap_name, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"]
        ]
        
        for rule in rules_to_remove:
            subprocess.run(rule, check=False)
            
        logger.debug("iptables rules cleaned up", 
                    tap_name=tap_name, 
                    default_interface=default_iface)
    
    def validate_network_connectivity(self, vm_id: str) -> Dict[str, Any]:
        """Validate network connectivity for a VM.
        
        Checks if the TAP interface is properly configured and accessible.
        
        Args:
            vm_id (str): VM identifier to validate
            
        Returns:
            Dict[str, Any]: Validation results with connectivity status
            
        Example:
            status = network_manager.validate_network_connectivity("abc123")
            if status["tap_interface_up"]:
                print("Interface is ready")
        """
        validation_results = {
            "vm_id": vm_id,
            "tap_interface_exists": False,
            "tap_interface_up": False,
            "gateway_ip_assigned": False,
            "ip_forwarding_enabled": False,
            "default_route_available": False
        }
        
        if vm_id not in self.active_interfaces:
            return validation_results
        
        interface_info = self.active_interfaces[vm_id]
        tap_name = interface_info["tap_name"]
        
        try:
            # Check if TAP interface exists and is up
            result = subprocess.run([
                "ip", "link", "show", tap_name
            ], capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                validation_results["tap_interface_exists"] = True
                validation_results["tap_interface_up"] = "UP" in result.stdout
            
            # Check if IP is assigned
            result = subprocess.run([
                "ip", "addr", "show", tap_name
            ], capture_output=True, text=True, check=False)
            
            if result.returncode == 0 and interface_info["gateway_ip"] in result.stdout:
                validation_results["gateway_ip_assigned"] = True
            
            # Check IP forwarding
            result = subprocess.run([
                "sysctl", "net.ipv4.ip_forward"
            ], capture_output=True, text=True, check=False)
            
            if result.returncode == 0 and "net.ipv4.ip_forward = 1" in result.stdout:
                validation_results["ip_forwarding_enabled"] = True
            
            # Check default route
            default_iface = self._get_default_interface()
            validation_results["default_route_available"] = default_iface is not None
            
        except Exception as e:
            logger.warning("Network validation error", vm_id=vm_id, error=str(e))
        
        return validation_results
    
    def get_interface_info(self, vm_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a VM's network interface.
        
        Args:
            vm_id (str): VM identifier
            
        Returns:
            Dict[str, Any]: Interface information, or None if not found
        """
        return self.active_interfaces.get(vm_id)
    
    def list_active_interfaces(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all active network interfaces.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary of all active interfaces
        """
        return self.active_interfaces.copy()
    
    def cleanup_all_networking(self) -> None:
        """Clean up all active network interfaces.
        
        Removes all TAP interfaces and associated iptables rules.
        Used for graceful shutdown of the entire system.
        """
        logger.info("Cleaning up all network interfaces", 
                   count=len(self.active_interfaces))
        
        # Clean up each interface
        vm_ids = list(self.active_interfaces.keys())
        for vm_id in vm_ids:
            self.cleanup_networking(vm_id)
        
        # Disable IP forwarding if no interfaces remain
        if not self.active_interfaces:
            try:
                subprocess.run([
                    "sudo", "sysctl", "-w", "net.ipv4.ip_forward=0"
                ], check=False)
                logger.debug("IP forwarding disabled")
            except Exception as e:
                logger.warning("Failed to disable IP forwarding", error=str(e))
        
        logger.success("All network interfaces cleaned up")