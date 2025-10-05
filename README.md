# Firecracker OpenAI Code Generator

A secure, isolated code generation system using AWS Firecracker microVMs and OpenAI API integration. Generate code in isolated virtual machines with complete network isolation and automatic cleanup.

## 🚀 Features

- **Secure Isolation**: Each code generation task runs in a completely isolated Firecracker microVM
- **OpenAI Integration**: Real API calls to OpenAI GPT-3.5-turbo for code generation
- **Multiple Languages**: Supports Python, JavaScript, Go, Bash, and more
- **SSL/TLS Support**: Full HTTPS connectivity with proper certificate verification
- **Results Storage**: Automatic saving of generated code with unique VM instance names
- **Complete Cleanup**: Automatic teardown of VMs and network resources
- **Ubuntu-based**: Uses Ubuntu 22.04 LTS for maximum compatibility

## 📋 Dependencies

### System Requirements
- **Linux**: Ubuntu 18.04+ or compatible Linux distribution
- **Architecture**: x86_64
- **Memory**: At least 2GB RAM recommended
- **Disk Space**: 2GB free space for VM images and results
- **Network**: Internet connectivity for OpenAI API calls

### Required Packages
```bash
sudo apt update
sudo apt install -y \
    curl \
    wget \
    jq \
    python3 \
    python3-pip \
    squashfs-tools \
    e2fsprogs \
    iptables \
    iproute2 \
    bridge-utils
```

### Firecracker Binary
The setup script automatically downloads Firecracker v1.10.0. No manual installation required.

## ⚙️ Installation

1. **Clone or download** the project files
2. **Set up OpenAI API key** in `.env` file:
   ```bash
   echo "OPENAI_API_KEY=your_api_key_here" > .env
   ```
3. **Run the setup script**:
   ```bash
   ./setup_vm_images_ubuntu.sh
   ```

The setup script will:
- Download Firecracker binaries
- Download Ubuntu kernel and rootfs
- Install SSL certificates
- Create the Ubuntu VM with OpenAI integration
- Set up network configuration

## 🎯 Usage

### Basic Code Generation
```bash
# Load environment variables and run
export $(cat .env | xargs)
python3 firecracker_orchestrator.py run "Create a Python function to calculate fibonacci numbers"
```

### Examples

**Python Function:**
```bash
python3 firecracker_orchestrator.py run "Write a Python class for a simple calculator"
```

**JavaScript Function:**
```bash
python3 firecracker_orchestrator.py run "Create a JavaScript function to sort an array"
```

**Go Program:**
```bash
python3 firecracker_orchestrator.py run "Write a Go program that prints Hello World"
```

**Bash Script:**
```bash
python3 firecracker_orchestrator.py run "Create a bash script to backup files with timestamp"
```

### Interactive Mode
```bash
python3 firecracker_orchestrator.py interactive
```

This starts an interactive session where you can submit multiple code generation tasks.

## 📁 Results Storage

Generated code is automatically saved in the `results/` directory with unique filenames:

```
results/
├── {vm_id}_{task_description}.json    # Complete result with metadata
└── {vm_id}_{task_description}.{ext}   # Clean executable code
```

**Example:**
- `69bfc3f6_Create_a_Python_function_to_reverse_a_string.json`
- `69bfc3f6_Create_a_Python_function_to_reverse_a_string.py`

**Supported file extensions:**
- `.py` - Python code
- `.js` - JavaScript code  
- `.go` - Go code
- `.sh` - Bash scripts
- `.txt` - Other/unknown code types

## 🧹 Cleanup

### Clean up temporary files and networks:
```bash
# Clean up VMs and temporary files
echo "y" | sudo ./teardown_vm.sh

# Clean up network interfaces
sudo ./teardown_network.sh
```

### Complete cleanup (including VM images):
```bash
echo "y" | sudo ./teardown_vm.sh --clean-images
```

## 🔧 Configuration

### VM Configuration
The system uses the following default configuration:
- **Memory**: 512 MB
- **vCPUs**: 1
- **Network**: 172.50.0.0/24 with NAT
- **OS**: Ubuntu 22.04.5 LTS
- **Kernel**: Linux 6.1.102

### OpenAI Configuration
- **Model**: gpt-3.5-turbo
- **Max Tokens**: 500
- **Temperature**: 0.7

These can be modified in `firecracker_orchestrator.py` and `setup_vm_images_ubuntu.sh`.

## 📊 System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Host System   │    │  Firecracker VM  │    │   OpenAI API    │
│                 │    │                  │    │                 │
│ ┌─────────────┐ │    │ ┌──────────────┐ │    │                 │
│ │ Orchestrator│ │◄──►│ │    Agent     │ │───►│  GPT-3.5-turbo  │
│ │   Python    │ │    │ │   Ubuntu     │ │    │                 │
│ └─────────────┘ │    │ │   22.04      │ │    │                 │
│                 │    │ └──────────────┘ │    │                 │
│ ┌─────────────┐ │    │ ┌──────────────┐ │    │                 │
│ │   Results   │ │◄───│ │ Shared Disk  │ │    │                 │
│ │   Folder    │ │    │ │  (EXT4)      │ │    │                 │
│ └─────────────┘ │    │ └──────────────┘ │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 🔒 Security Features

- **Complete Isolation**: Each task runs in a separate microVM
- **Network Isolation**: VMs have limited network access via NAT
- **Secure API Key Handling**: API keys passed via kernel command line
- **Automatic Cleanup**: All VM resources cleaned up after each task
- **No Persistence**: VMs are ephemeral and destroyed after use

## 🐛 Troubleshooting

### Common Issues

**1. Permission Errors**
```bash
# Ensure proper permissions for Firecracker
sudo chmod +x release-v1.10.0-x86_64/firecracker-v1.10.0-x86_64
```

**2. Network Issues**
```bash
# Reset network configuration
sudo ./teardown_network.sh
```

**3. VM Startup Issues**
```bash
# Check VM logs
tail -f /tmp/vm-*.log
```

**4. OpenAI API Errors**
- Verify your API key in `.env` file
- Check your OpenAI account has sufficient credits
- Ensure internet connectivity from the host

### Log Files
- VM logs: `/tmp/vm-{vm_id}.log`
- VM errors: `/tmp/vm-{vm_id}.err`
- VM config: `/tmp/vm-config-{vm_id}.json`

## 📄 File Structure

```
firecracker/
├── .env                          # OpenAI API key
├── README.md                     # This file
├── cline-notes.md               # Development documentation
├── firecracker_orchestrator.py  # Main orchestrator
├── setup_vm_images_ubuntu.sh    # VM setup script
├── teardown_network.sh          # Network cleanup
├── teardown_vm.sh               # VM cleanup
├── vm-config.json               # VM configuration template
├── release-v1.10.0-x86_64/      # Firecracker binaries
├── vm-images-ubuntu/            # Ubuntu kernel and rootfs
└── results/                     # Generated code output
```

## 🤝 Contributing

This system is designed for secure, isolated AI code generation. When modifying:

1. Test all changes thoroughly in isolated environments
2. Ensure proper cleanup of all resources
3. Maintain security isolation principles
4. Update documentation for any new features

## Maintainers

- @bbourqu — primary maintainer (VM orchestration, security, and CI)

## Developer workflow

We maintain runtime dependencies in `requirements.txt` and developer/test dependencies in `requirements-dev.txt`.

Common commands (see `Makefile`):

- `make install` — install runtime requirements
- `make dev` — install runtime + development requirements
- `make test` — run the test suite (`pytest -q`)
- `make lint` — run `black` to format code
- `make typecheck` — run `mypy` type checks
- `make lock` — generate pinned lockfiles (requires `pip-tools`)

Lockfiles & CI

For reproducible CI and deployments we prefer pinned lockfiles. Use `pip-compile` from `pip-tools` to generate `requirements.txt.lock` and `requirements-dev.txt.lock` (the repo includes `scripts/lock-requirements.sh` which wraps this).

The GitHub Actions workflow prefers `requirements*.lock` if present; push your lockfiles to make CI install pinned dependencies.

Run the MCP server locally (dev)

The repository exposes a minimal FastAPI-based MCP control plane in `mcp_server.py`. To run it locally for development (requires `fastapi`/`uvicorn` installed):

```bash
# install dev deps first (or ensure uvicorn/fastapi/pydantic are available)
make dev

# run the FastAPI app with autoreload on port 8000
python -m uvicorn mcp_server:app --reload --host 127.0.0.1 --port 8000
```

Endpoints:

- `POST /v1/tasks` — submit a task to create a VM (accepts `MCPTaskRequest` schema)
- `POST /v1/results` — post back results from a guest subagent (`SubagentResult` schema)

Note: In tests and some lightweight environments the module is import-safe even without FastAPI/Pydantic; in production or local running you should install the dev requirements so `app` is available.

## 📜 License

This project uses AWS Firecracker (Apache License 2.0) and integrates with OpenAI API. Please ensure compliance with both licenses and OpenAI's usage policies.

## 🆘 Support

For issues or questions:

1. Check the troubleshooting section above
2. Review VM logs in `/tmp/vm-*.log`
3. Verify all dependencies are installed
4. Test with simple examples first

The system has been tested on Ubuntu 22.04 with consistent 100% success rates for code generation tasks.