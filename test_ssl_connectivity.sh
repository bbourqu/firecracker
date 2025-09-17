#!/bin/bash
echo "=== Testing SSL Connectivity ==="

# Setup network
./setup_network.sh

# Create socket path
SOCKET_PATH="/tmp/firecracker-ssl-test.socket"
rm -f $SOCKET_PATH

echo "Starting Firecracker VM with SSL test..."
timeout 120 firecracker --api-sock $SOCKET_PATH --config-file vm-config.json

echo "=== SSL Test Complete ==="
