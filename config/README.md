# Configuration Files

This directory contains configuration files for the Firecracker OpenAI Code Generator.

## File Structure

- **`default.yaml`** - Base configuration with sensible defaults
- **`development.yaml`** - Development environment overrides (debug logging, faster timeouts)
- **`production.yaml`** - Production environment overrides (structured logging, higher limits)
- **`schema.py`** - Configuration validation and type definitions

## Usage

### Use Default Configuration
```bash
python3 firecracker_orchestrator.py run "Create Python code"
```

### Use Development Configuration  
```bash
python3 firecracker_orchestrator.py --config-path=config --config-name=development run "Create code"
```

### Use Production Configuration
```bash
python3 firecracker_orchestrator.py --config-path=config --config-name=production run "Create code"
```

### Override Specific Values
```bash
# Override VM memory
python3 firecracker_orchestrator.py --config.vm.memory_mb=1024 run "Create code"

# Override logging level
python3 firecracker_orchestrator.py --config.logging.level=DEBUG run "Create code"

# Multiple overrides
python3 firecracker_orchestrator.py \
    --config.vm.memory_mb=2048 \
    --config.logging.level=DEBUG \
    --config.openai.temperature=0.9 \
    run "Create advanced code"
```

### Environment Variables
```bash
# Override via environment variables
export FIRECRACKER_VM_MEMORY_MB=2048
export FIRECRACKER_LOGGING_LEVEL=DEBUG
python3 firecracker_orchestrator.py run "Create code"
```

## Configuration Sections

### VM Configuration
- `memory_mb`: VM memory allocation (128-16384 MB)
- `vcpus`: Number of virtual CPUs (1-32)
- `timeout`: VM operation timeout
- `network_cidr`: Network CIDR for VM networking

### OpenAI Configuration
- `model`: OpenAI model to use
- `max_tokens`: Maximum response tokens
- `temperature`: Creativity level (0.0-2.0)
- `timeout`: API request timeout

### Logging Configuration
- `level`: Log level (DEBUG, INFO, WARNING, ERROR)
- `format`: Output format (simple, detailed, json)
- `file`: Optional log file path
- `rotation`: Log file rotation size

### Paths Configuration
- `vm_images`: VM image directory
- `ubuntu_images`: Ubuntu VM images
- `results`: Results output directory
- `temp`: Temporary files directory

## Validation

Configuration files are automatically validated using the schema defined in `schema.py`. Invalid configurations will show helpful error messages at startup.