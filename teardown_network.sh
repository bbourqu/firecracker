#!/bin/bash

# Firecracker Network Teardown Script
# This script removes the network configuration added for Firecracker VMs

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to remove NAT rules
cleanup_nat_rules() {
    print_status "Removing Firecracker NAT rules..."
    
    # Check if the rule exists
    if sudo iptables -t nat -C POSTROUTING -s 172.16.0.0/24 -o eth0 -j MASQUERADE 2>/dev/null; then
        # Remove the NAT rule
        sudo iptables -t nat -D POSTROUTING -s 172.16.0.0/24 -o eth0 -j MASQUERADE
        print_success "Removed NAT MASQUERADE rule for 172.16.0.0/24"
    else
        print_warning "NAT MASQUERADE rule for 172.16.0.0/24 not found"
    fi
}

# Function to remove any remaining TAP interfaces
cleanup_tap_interfaces() {
    print_status "Cleaning up any remaining TAP interfaces..."
    
    # Find and remove any tap interfaces starting with "tap"
    for tap_if in $(ip link show | grep -o 'tap[a-f0-9]*' | head -10); do
        if ip link show "$tap_if" >/dev/null 2>&1; then
            print_status "Removing TAP interface: $tap_if"
            sudo ip link delete "$tap_if" 2>/dev/null || true
        fi
    done
    
    print_success "TAP interface cleanup completed"
}

# Function to disable IP forwarding
disable_ip_forwarding() {
    print_status "Disabling IP forwarding..."
    
    # Check current state
    current_forward=$(cat /proc/sys/net/ipv4/ip_forward)
    if [ "$current_forward" -eq 1 ]; then
        # Disable IP forwarding
        echo 0 | sudo tee /proc/sys/net/ipv4/ip_forward > /dev/null
        print_success "Disabled IP forwarding"
    else
        print_status "IP forwarding was already disabled"
    fi
}

# Function to verify network state
verify_cleanup() {
    print_status "Verifying network cleanup..."
    
    # Check NAT rules
    nat_rules=$(sudo iptables -t nat -L POSTROUTING -n | grep "172.16.0.0/24" | wc -l)
    if [ "$nat_rules" -eq 0 ]; then
        print_success "✓ No Firecracker NAT rules remaining"
    else
        print_warning "! Some NAT rules may still exist"
    fi
    
    # Check TAP interfaces
    tap_count=$(ip link show | grep -c "tap[a-f0-9]*" || true)
    if [ "$tap_count" -eq 0 ]; then
        print_success "✓ No TAP interfaces remaining"
    else
        print_warning "! $tap_count TAP interfaces still exist"
    fi
    
    # Check IP forwarding
    ip_forward=$(cat /proc/sys/net/ipv4/ip_forward)
    if [ "$ip_forward" -eq 0 ]; then
        print_success "✓ IP forwarding is disabled"
    else
        print_warning "! IP forwarding is still enabled"
    fi
}

# Function to display current network state
show_network_state() {
    print_status "Current network state:"
    echo ""
    echo "NAT rules:"
    sudo iptables -t nat -L POSTROUTING -n | grep -E "(Chain|MASQUERADE)" || echo "  No MASQUERADE rules"
    echo ""
    echo "TAP interfaces:"
    ip link show | grep "tap" || echo "  No TAP interfaces"
    echo ""
    echo "IP forwarding: $(cat /proc/sys/net/ipv4/ip_forward)"
}

# Main execution
main() {
    print_status "Starting Firecracker network teardown..."
    echo ""
    
    # Show current state
    show_network_state
    echo ""
    
    # Perform cleanup
    cleanup_nat_rules
    cleanup_tap_interfaces
    disable_ip_forwarding
    
    # Verify cleanup
    echo ""
    verify_cleanup
    
    echo ""
    print_success "Network teardown completed!"
    echo ""
    print_status "Final network state:"
    show_network_state
}

# Check for sudo access
if ! sudo -n true 2>/dev/null; then
    print_warning "This script requires sudo access"
    print_status "You may be prompted for your password"
fi

# Run main function
main "$@"
