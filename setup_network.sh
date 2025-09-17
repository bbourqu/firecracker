#!/bin/bash
echo "Setting up Firecracker network..."

# Create TAP interface
sudo ip tuntap add tap-firecracker mode tap
sudo ip addr add 172.50.0.1/24 dev tap-firecracker
sudo ip link set tap-firecracker up

# Setup NAT and forwarding
sudo iptables -t nat -A POSTROUTING -s 172.50.0.0/24 -j MASQUERADE
sudo iptables -A FORWARD -i tap-firecracker -o eth0 -j ACCEPT
sudo iptables -A FORWARD -i eth0 -o tap-firecracker -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo sysctl -w net.ipv4.ip_forward=1

echo "Network setup complete"
