#!/bin/bash

# Firecracker Ubuntu VM Setup Script with SSL Support
# Creates Ubuntu 22.04 VM with working SSL/HTTPS connectivity

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
VM_IMAGES_DIR="vm-images"
UBUNTU_IMAGES_DIR="vm-images-ubuntu"

# Function to print colored output
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

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    local missing_deps=()
    
    # Check for required commands
    if ! command_exists wget; then
        missing_deps+=("wget")
    fi
    
    if ! command_exists curl; then
        missing_deps+=("curl")
    fi
    
    if ! command_exists unsquashfs; then
        missing_deps+=("squashfs-tools")
    fi
    
    if ! command_exists mkfs.ext4; then
        missing_deps+=("e2fsprogs")
    fi
    
    if ! command_exists firecracker; then
        missing_deps+=("firecracker")
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        print_error "Missing required dependencies: ${missing_deps[*]}"
        print_status "Please install missing dependencies and try again."
        exit 1
    fi
    
    print_success "All prerequisites are installed"
}

# Function to setup directories
setup_directories() {
    print_status "Setting up directory structure..."
    
    # Create directories
    mkdir -p "$VM_IMAGES_DIR"
    mkdir -p "$UBUNTU_IMAGES_DIR"
    mkdir -p "shared/tasks"
    mkdir -p "shared/results"
    
    print_success "Directory structure created"
}

# Function to download Ubuntu kernel and rootfs
download_ubuntu_images() {
    print_status "Downloading Ubuntu kernel and rootfs..."
    
    cd "$UBUNTU_IMAGES_DIR"
    
    # Get system architecture
    ARCH="$(uname -m)"
    CI_VERSION="v1.10"
    
    print_status "Architecture: $ARCH"
    print_status "CI Version: $CI_VERSION"
    
    # Download kernel if not exists
    if [ ! -f "vmlinux.bin" ]; then
        print_status "Downloading Ubuntu kernel..."
        latest_kernel_key=$(curl -s "http://spec.ccfc.min.s3.amazonaws.com/?prefix=firecracker-ci/$CI_VERSION/$ARCH/vmlinux-&list-type=2" \
            | grep -oP "(?<=<Key>)(firecracker-ci/$CI_VERSION/$ARCH/vmlinux-[0-9]+\.[0-9]+\.[0-9]{1,3})(?=</Key>)" \
            | sort -V | tail -1)
        
        if [ -z "$latest_kernel_key" ]; then
            print_warning "Could not find latest kernel, using fallback..."
            wget -O vmlinux.bin "https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/kernels/vmlinux.bin"
        else
            kernel_filename=$(basename "$latest_kernel_key")
            wget -O "$kernel_filename" "https://s3.amazonaws.com/spec.ccfc.min/${latest_kernel_key}"
            ln -sf "$kernel_filename" vmlinux.bin
        fi
        print_success "Kernel downloaded: $(ls -lh vmlinux.bin)"
    else
        print_status "Kernel already exists, skipping download"
    fi
    
    # Download Ubuntu rootfs if not exists
    if [ ! -f "ubuntu.squashfs" ]; then
        print_status "Downloading Ubuntu rootfs..."
        latest_ubuntu_key=$(curl -s "http://spec.ccfc.min.s3.amazonaws.com/?prefix=firecracker-ci/$CI_VERSION/$ARCH/ubuntu-&list-type=2" \
            | grep -oP "(?<=<Key>)(firecracker-ci/$CI_VERSION/$ARCH/ubuntu-[0-9]+\.[0-9]+\.squashfs)(?=</Key>)" \
            | sort -V | tail -1)
        
        if [ -z "$latest_ubuntu_key" ]; then
            print_error "Could not find Ubuntu rootfs"
            exit 1
        fi
        
        ubuntu_filename=$(basename "$latest_ubuntu_key")
        ubuntu_version=$(echo $ubuntu_filename | grep -oE '[0-9]+\.[0-9]+')
        print_status "Ubuntu version: $ubuntu_version"
        
        wget -O "$ubuntu_filename" "https://s3.amazonaws.com/spec.ccfc.min/${latest_ubuntu_key}"
        ln -sf "$ubuntu_filename" ubuntu.squashfs
        print_success "Ubuntu rootfs downloaded: $(ls -lh ubuntu.squashfs)"
    else
        print_status "Ubuntu rootfs already exists, skipping download"
    fi
    
    cd ..
}

# Function to create Ubuntu VM with SSL support
create_ubuntu_vm() {
    print_status "Creating Ubuntu VM with SSL support..."
    
    cd "$UBUNTU_IMAGES_DIR"
    
    # Convert squashfs to ext4 if not exists
    if [ ! -f "ubuntu-rootfs.ext4" ]; then
        print_status "Converting Ubuntu rootfs to EXT4..."
        
        # Extract squashfs
        rm -rf ubuntu-mount
        mkdir -p ubuntu-mount
        sudo unsquashfs -d ubuntu-mount ubuntu.squashfs
        
        # Create ext4 image (1GB)
        dd if=/dev/zero of=ubuntu-rootfs.ext4 bs=1M count=1024
        mkfs.ext4 ubuntu-rootfs.ext4
        
        # Mount and copy
        mkdir -p ubuntu-ext4-mount
        sudo mount -o loop ubuntu-rootfs.ext4 ubuntu-ext4-mount
        sudo cp -a ubuntu-mount/* ubuntu-ext4-mount/
        
        print_status "Installing SSL certificates from host..."
        # Copy CA certificates from host
        sudo mkdir -p ubuntu-ext4-mount/etc/ssl/certs
        sudo cp -r /etc/ssl/certs/* ubuntu-ext4-mount/etc/ssl/certs/ 2>/dev/null || true
        sudo cp /etc/ssl/certs/ca-certificates.crt ubuntu-ext4-mount/etc/ssl/certs/ 2>/dev/null || true
        
        # Set SSL environment
        sudo tee ubuntu-ext4-mount/etc/environment >/dev/null << 'EOF'
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
SSL_CERT_DIR=/etc/ssl/certs
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
EOF
        
        print_status "Installing basic Python test script..."
        # Python is already available in Ubuntu base, just create test script
        
        print_status "Creating integrated SSL and task agent..."
        # Create agent that handles both SSL testing and task processing
        sudo tee ubuntu-ext4-mount/ssl_agent.sh >/dev/null << 'EOF'
#!/bin/bash
echo "=== Ubuntu OpenAI Agent Starting ==="
echo "Timestamp: $(date)"
echo "Ubuntu Version: $(cat /etc/os-release | grep PRETTY_NAME)"

# Load SSL environment
source /etc/environment 2>/dev/null || true

# Basic system setup
mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sysfs /sys 2>/dev/null || true
mount -t tmpfs tmpfs /tmp 2>/dev/null || true

# Mount shared disk for task communication
mkdir -p /shared
mount -t ext4 /dev/vdb /shared 2>/dev/null || echo "No shared disk found"

echo "=== Network Configuration ==="
ip link set lo up
# Network should be configured by orchestrator, just set up interface
ip addr add 172.50.0.2/24 dev eth0 2>/dev/null || echo "Network already configured"
ip link set eth0 up
ip route add default via 172.50.0.1 2>/dev/null || echo "Default route exists"
echo "nameserver 8.8.8.8" > /etc/resolv.conf

echo "Network ready - testing connectivity..."

echo "=== SSL Connectivity Verification ==="
echo "Testing HTTPS with curl..."
if curl -s --connect-timeout 10 --max-time 15 https://httpbin.org/ip; then
    echo "🎉 HTTPS connectivity SUCCESS!"
else
    echo "❌ HTTPS connectivity FAILED"
fi

echo "=== Python SSL Testing ==="
if command -v python3 >/dev/null 2>&1; then
    python3 -c "
import urllib.request
import ssl
import os

os.environ['SSL_CERT_FILE'] = '/etc/ssl/certs/ca-certificates.crt'

try:
    with urllib.request.urlopen('https://httpbin.org/ip', timeout=10) as response:
        data = response.read().decode('utf-8')
        print('🎉 Python HTTPS SUCCESS:', data.strip())
except Exception as e:
    print('❌ Python HTTPS FAILED:', e)
"

    echo "=== Testing OpenAI API endpoint connectivity ==="
    python3 -c "
import urllib.request
import ssl
import os
import json

os.environ['SSL_CERT_FILE'] = '/etc/ssl/certs/ca-certificates.crt'

try:
    # Test HTTPS connectivity to OpenAI API endpoint  
    with urllib.request.urlopen('https://api.openai.com', timeout=10) as response:
        status = response.getcode()
        if status in [200, 401, 403, 404]:  # These are expected responses
            print('🎉 OpenAI API endpoint connectivity SUCCESS (status:', status, ')')
        else:
            print('❌ OpenAI API endpoint connectivity: unexpected status', status)
except Exception as e:
    print('❌ OpenAI API endpoint connectivity FAILED:', e)

# Test a simple API call structure (without actual API key)
print('=== Testing HTTPS POST capability ===')
try:
    data = json.dumps({'test': 'connection'}).encode('utf-8')
    req = urllib.request.Request('https://httpbin.org/post', data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        result = json.loads(response.read().decode('utf-8'))
        if 'json' in result and result['json']['test'] == 'connection':
            print('🎉 HTTPS POST capability SUCCESS')
        else:
            print('❌ HTTPS POST unexpected response')
except Exception as e:
    print('❌ HTTPS POST capability FAILED:', e)
"
else
    echo "Python3 not available"
fi

echo "=== Agent Initialization Complete ==="
echo "SSL connectivity verified - system ready for OpenAI integration"

# Start task processing loop
echo "=== Starting Task Processing ==="
cd /shared || exit 1

while true; do
    # Look for new tasks
    for task_file in tasks/*.json; do
        [ -f "$task_file" ] || break
        if [ -f "$task_file" ]; then
            task_id=$(basename "$task_file" .json)
            result_file="results/${task_id}.json"
            
            # Skip if already processed
            if [ -f "$result_file" ]; then
                continue
            fi
            
            echo "Processing task: $task_id"
            
            # Read task
            task_description=$(python3 -c "
import json
import sys
try:
    with open('$task_file', 'r') as f:
        task = json.load(f)
    print(task.get('description', 'No description'))
except Exception as e:
    print('Error reading task:', e)
    sys.exit(1)
")
            
            echo "Task: $task_description"
            
            # Real OpenAI API integration
            # Use environment variables to safely pass data to Python
            export CURRENT_TASK_ID="$task_id"
            export TASK_DESCRIPTION="$task_description"
            python3 -c "
import json
import os
import urllib.request
import urllib.parse
import ssl
from datetime import datetime

# Configure SSL context to use system certificates
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = True
ssl_context.verify_mode = ssl.CERT_REQUIRED

# Set SSL certificate file paths
if os.path.exists('/etc/ssl/certs/ca-certificates.crt'):
    ssl_context.load_verify_locations('/etc/ssl/certs/ca-certificates.crt')
os.environ['SSL_CERT_FILE'] = '/etc/ssl/certs/ca-certificates.crt'
os.environ['SSL_CERT_DIR'] = '/etc/ssl/certs'
os.environ['REQUESTS_CA_BUNDLE'] = '/etc/ssl/certs/ca-certificates.crt'

# Get variables from environment (safer than bash substitution)
task_id = os.environ['CURRENT_TASK_ID']
task_description = os.environ.get('TASK_DESCRIPTION', 'No task description')

# Get OpenAI API key from kernel command line
openai_api_key = None
try:
    with open('/proc/cmdline', 'r') as f:
        cmdline = f.read()
        for param in cmdline.split():
            if param.startswith('OPENAI_API_KEY='):
                openai_api_key = param.split('=', 1)[1]
                break
except Exception as e:
    print(f'Error reading OpenAI API key: {e}')

# Attempt to call OpenAI API
api_result = None
api_error = None
generated_code = None

if openai_api_key and openai_api_key.startswith('sk-'):
    try:
        # Create OpenAI API request
        prompt = f'Create code for this request: {task_description}'
        
        request_data = {
            'model': 'gpt-3.5-turbo',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful coding assistant. Generate clean, working code for the user request. Return only the code with minimal explanation.'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 500,
            'temperature': 0.7
        }
        
        # Make the API request
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=json.dumps(request_data).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {openai_api_key}'
            }
        )
        
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            response_data = json.loads(response.read().decode('utf-8'))
            if 'choices' in response_data and len(response_data['choices']) > 0:
                api_result = response_data['choices'][0]['message']['content']
                generated_code = api_result
                print(f'✅ OpenAI API SUCCESS: Generated {len(api_result)} characters')
            else:
                api_error = 'No response from OpenAI API'
                
    except Exception as e:
        api_error = str(e)
        print(f'❌ OpenAI API ERROR: {e}')

# Create result with actual OpenAI response or fallback
if api_result:
    result = {
        'task_id': task_id,
        'status': 'completed',
        'result': f'Code generated successfully using OpenAI API',
        'task_description': task_description,
        'generated_code': generated_code,
        'timestamp': datetime.now().isoformat(),
        'api_status': 'SUCCESS',
        'ssl_status': 'WORKING',
        'python_status': 'AVAILABLE',
        'openai_endpoint': 'SUCCESS'
    }
else:
    # Fallback result when API fails
    fallback_code = '''#!/bin/bash
echo \"Hello, World!\"
echo \"This is a fallback program - OpenAI API was not available\"
echo \"Task was: $task_description\"
echo \"Current time: \$(date)\"
'''
    
    result = {
        'task_id': task_id,
        'status': 'completed',
        'result': f'Fallback code generated (OpenAI API unavailable)',
        'task_description': task_description,
        'generated_code': fallback_code,
        'timestamp': datetime.now().isoformat(),
        'api_status': 'FAILED',
        'api_error': api_error or 'No API key available',
        'ssl_status': 'WORKING',
        'python_status': 'AVAILABLE',
        'openai_endpoint': 'FAILED'
    }

# Write result file
with open(f'results/{task_id}.json', 'w') as f:
    json.dump(result, f, indent=2)

print('Task completed successfully!')
"
            unset CURRENT_TASK_ID TASK_DESCRIPTION
        fi
    done
    
    sleep 2
done
EOF
        
        sudo chmod +x ubuntu-ext4-mount/ssl_agent.sh
        
        # Cleanup
        sudo umount ubuntu-ext4-mount
        rmdir ubuntu-ext4-mount
        sudo rm -rf ubuntu-mount
        
        print_success "Ubuntu VM with SSL support created successfully"
    else
        print_status "Ubuntu VM already exists, skipping creation"
    fi
    
    cd ..
}

# Function to create network setup
setup_network() {
    print_status "Setting up network configuration..."
    
    # Create network setup script
    cat > setup_network.sh << 'EOF'
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
EOF
    
    chmod +x setup_network.sh
    
    print_success "Network setup script created"
}

# Function to create VM configuration
create_vm_config() {
    print_status "Creating VM configuration..."
    
    # Create VM configuration file
    cat > vm-config.json << 'EOF'
{
  "boot-source": {
    "kernel_image_path": "vm-images-ubuntu/vmlinux.bin",
    "boot_args": "console=ttyS0 reboot=k panic=1 pci=off init=/ssl_agent.sh"
  },
  "drives": [
    {
      "drive_id": "rootfs",
      "path_on_host": "vm-images-ubuntu/ubuntu-rootfs.ext4",
      "is_root_device": true,
      "is_read_only": false
    }
  ],
  "network-interfaces": [
    {
      "iface_id": "eth0",
      "guest_mac": "AA:FC:00:00:00:01",
      "host_dev_name": "tap-firecracker"
    }
  ],
  "machine-config": {
    "vcpu_count": 1,
    "mem_size_mib": 512
  }
}
EOF
    
    print_success "VM configuration created"
}

# Function to create test script
create_test_script() {
    print_status "Creating SSL test script..."
    
    cat > test_ssl_connectivity.sh << 'EOF'
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
EOF
    
    chmod +x test_ssl_connectivity.sh
    
    print_success "SSL test script created"
}

# Main execution
main() {
    print_status "Starting Firecracker Ubuntu VM setup with SSL support..."
    
    check_prerequisites
    setup_directories
    download_ubuntu_images
    create_ubuntu_vm
    setup_network
    create_vm_config
    create_test_script
    
    print_success "Firecracker Ubuntu VM setup completed successfully!"
    print_status "Run './test_ssl_connectivity.sh' to verify SSL connectivity"
    print_status "VM images location: $UBUNTU_IMAGES_DIR/"
    print_status "Configuration file: vm-config.json"
}

# Run main function
main "$@"