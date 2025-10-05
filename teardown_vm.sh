#!/bin/bash

# Firecracker VM Teardown Script
# This script cleans up VM resources, processes, and temporary files

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
VM_IMAGES_DIR="vm-images"
SHARED_DIR="shared"
TEMP_PATTERN="/tmp/firecracker-*"
VM_LOG_PATTERN="/tmp/vm-*.log"
VM_ERR_PATTERN="/tmp/vm-*.err"
VM_CONFIG_PATTERN="/tmp/vm-config-*.json"
SHARED_DISK_PATTERN="/tmp/shared-*.ext4"
SHARED_MOUNT_PATTERN="/tmp/shared-mount-*"

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

# Function to kill running Firecracker processes
kill_firecracker_processes() {
    print_status "Checking for running Firecracker processes..."
    
    local firecracker_pids=$(pgrep -f "firecracker" 2>/dev/null || true)
    
    if [ -n "$firecracker_pids" ]; then
        print_warning "Found running Firecracker processes: $firecracker_pids"
        
        # Try graceful termination first
        print_status "Attempting graceful termination..."
        echo "$firecracker_pids" | xargs -r kill -TERM 2>/dev/null || true
        
        # Wait a moment for graceful shutdown
        sleep 3
        
        # Check if any processes are still running
        local remaining_pids=$(pgrep -f "firecracker" 2>/dev/null || true)
        
        if [ -n "$remaining_pids" ]; then
            print_warning "Force killing remaining processes: $remaining_pids"
            echo "$remaining_pids" | xargs -r kill -KILL 2>/dev/null || true
        fi
        
        print_success "Firecracker processes terminated"
    else
        print_status "No running Firecracker processes found"
    fi
}

# Function to clean up network interfaces
cleanup_network_interfaces() {
    print_status "Cleaning up network interfaces..."
    
    local tap_interfaces=$(ip link show | grep -o "tap[a-f0-9]\{8\}" 2>/dev/null || true)
    
    if [ -n "$tap_interfaces" ]; then
        print_status "Found TAP interfaces to clean up: $tap_interfaces"
        
        for interface in $tap_interfaces; do
            print_status "Removing interface: $interface"
            sudo ip link delete "$interface" 2>/dev/null || {
                print_warning "Failed to remove interface $interface (may not exist)"
            }
        done
        
        print_success "Network interfaces cleaned up"
    else
        print_status "No TAP interfaces found to clean up"
    fi
}

# Function to unmount any mounted shared disks
unmount_shared_disks() {
    print_status "Checking for mounted shared disks..."
    
    # Find mounted shared disk mount points
    local mounted_points=$(mount | grep -o "/tmp/shared-mount-[a-f0-9]\{8\}" 2>/dev/null || true)
    
    if [ -n "$mounted_points" ]; then
        print_warning "Found mounted shared disks: $mounted_points"
        
        for mount_point in $mounted_points; do
            print_status "Unmounting: $mount_point"
            sudo umount "$mount_point" 2>/dev/null || {
                print_warning "Failed to unmount $mount_point (may not be mounted)"
            }
            
            # Remove mount point directory
            if [ -d "$mount_point" ]; then
                sudo rmdir "$mount_point" 2>/dev/null || {
                    print_warning "Failed to remove mount point directory $mount_point"
                }
            fi
        done
        
        print_success "Shared disks unmounted"
    else
        print_status "No mounted shared disks found"
    fi
}

# Function to clean up temporary files
cleanup_temp_files() {
    print_status "Cleaning up temporary files..."
    
    local files_removed=0
    
    # Clean up VM log files
    for pattern in "$VM_LOG_PATTERN" "$VM_ERR_PATTERN" "$VM_CONFIG_PATTERN"; do
        local files=$(ls $pattern 2>/dev/null || true)
        if [ -n "$files" ]; then
            print_status "Removing files matching: $pattern"
            rm -f $pattern 2>/dev/null || true
            files_removed=$((files_removed + $(echo "$files" | wc -w)))
        fi
    done
    
    # Clean up shared disk images
    local shared_disks=$(ls $SHARED_DISK_PATTERN 2>/dev/null || true)
    if [ -n "$shared_disks" ]; then
        print_status "Removing shared disk images: $SHARED_DISK_PATTERN"
        rm -f $SHARED_DISK_PATTERN 2>/dev/null || true
        files_removed=$((files_removed + $(echo "$shared_disks" | wc -w)))
    fi
    
    # Clean up any remaining mount point directories
    local mount_dirs=$(ls -d $SHARED_MOUNT_PATTERN 2>/dev/null || true)
    if [ -n "$mount_dirs" ]; then
        print_status "Removing mount point directories: $SHARED_MOUNT_PATTERN"
        sudo rm -rf $SHARED_MOUNT_PATTERN 2>/dev/null || true
        files_removed=$((files_removed + $(echo "$mount_dirs" | wc -w)))
    fi
    
    # Clean up Firecracker socket files
    local socket_files=$(ls /tmp/firecracker-*.socket 2>/dev/null || true)
    if [ -n "$socket_files" ]; then
        print_status "Removing Firecracker socket files"
        rm -f /tmp/firecracker-*.socket 2>/dev/null || true
        files_removed=$((files_removed + $(echo "$socket_files" | wc -w)))
    fi
    
    # Clean up build temporary directories
    if [ -d "/tmp/firecracker-vm-build" ]; then
        print_status "Removing build temporary directory"
        rm -rf "/tmp/firecracker-vm-build" 2>/dev/null || true
        files_removed=$((files_removed + 1))
    fi
    
    if [ $files_removed -gt 0 ]; then
        print_success "Removed $files_removed temporary files/directories"
    else
        print_status "No temporary files found to clean up"
    fi
}

# Function to clean up shared directories
cleanup_shared_directories() {
    print_status "Cleaning up shared directories..."
    
    if [ -d "$SHARED_DIR" ]; then
        local task_files=$(find "$SHARED_DIR/tasks" -name "*.json" 2>/dev/null | wc -l)
        local result_files=$(find "$SHARED_DIR/results" -name "*.json" 2>/dev/null | wc -l)
        
        if [ $task_files -gt 0 ] || [ $result_files -gt 0 ]; then
            print_status "Found $task_files task files and $result_files result files"
            
            # Remove task and result files
            rm -f "$SHARED_DIR/tasks"/*.json 2>/dev/null || true
            rm -f "$SHARED_DIR/results"/*.json 2>/dev/null || true
            
            print_success "Cleaned up shared directory files"
        else
            print_status "No files found in shared directories"
        fi
        
        # Remove the entire shared directory structure
        if [ -d "$SHARED_DIR" ]; then
            rm -rf "$SHARED_DIR"
            print_success "Removed shared directory: $SHARED_DIR"
        fi
    else
        print_status "Shared directory does not exist"
    fi
}

# Function to clean up VM images (optional)
cleanup_vm_images() {
    print_status "VM images cleanup (optional)..."
    
    if [ -d "$VM_IMAGES_DIR" ]; then
        local kernel_size=0
        local rootfs_size=0
        
        if [ -f "$VM_IMAGES_DIR/vmlinux.bin" ]; then
            kernel_size=$(stat -c%s "$VM_IMAGES_DIR/vmlinux.bin" 2>/dev/null || echo 0)
        fi
        
        if [ -f "$VM_IMAGES_DIR/rootfs-python-openai.ext4" ]; then
            rootfs_size=$(stat -c%s "$VM_IMAGES_DIR/rootfs-python-openai.ext4" 2>/dev/null || echo 0)
        fi
        
        local total_size=$((kernel_size + rootfs_size))
        
        if [ $total_size -gt 0 ]; then
            print_status "VM images found ($(($total_size / 1024 / 1024)) MB total)"
            print_status "Use --clean-images to remove VM images"
        else
            print_status "No VM images found"
        fi
    else
        print_status "VM images directory does not exist"
    fi
}

# Function to remove VM images
remove_vm_images() {
    print_status "Removing VM images..."
    
    local files_removed=0
    
    if [ -d "$VM_IMAGES_DIR" ]; then
        # Remove generated VM images
        local vm_files=(
            "$VM_IMAGES_DIR/vmlinux.bin"
            "$VM_IMAGES_DIR/vmlinuz"
            "$VM_IMAGES_DIR/rootfs-python-openai.ext4"
            "$VM_IMAGES_DIR/rootfs-python.ext4"
            "$VM_IMAGES_DIR/rootfs.ext4"
            "$VM_IMAGES_DIR/alpine-kernel.iso"
            "$VM_IMAGES_DIR/alpine-minirootfs.tar.gz"
            "$VM_IMAGES_DIR/alpine-python-openai-rootfs.tar.gz"
            "$VM_IMAGES_DIR/alpine-python-rootfs.tar.gz"
            "$VM_IMAGES_DIR/initramfs"
        )
        
        for file in "${vm_files[@]}"; do
            if [ -f "$file" ]; then
                print_status "Removing: $file"
                rm -f "$file"
                files_removed=$((files_removed + 1))
            fi
        done
        
        # Remove empty directories if they exist
        if [ -d "$VM_IMAGES_DIR" ] && [ -z "$(ls -A "$VM_IMAGES_DIR" 2>/dev/null)" ]; then
            print_status "Removing empty VM images directory"
            rmdir "$VM_IMAGES_DIR"
        fi
        
        print_success "Removed $files_removed VM image files"
    else
        print_status "VM images directory does not exist"
    fi
}

# Function to display system status
show_status() {
    print_status "Current system status:"
    echo ""
    
    # Check for running processes
    local firecracker_count=$(pgrep -f "firecracker" 2>/dev/null | wc -l)
    echo "  Firecracker processes: $firecracker_count"
    
    # Check for network interfaces
    local tap_count=$(ip link show | grep -c "tap[a-f0-9]\{8\}" 2>/dev/null || echo 0)
    echo "  TAP interfaces: $tap_count"
    
    # Check for mounted disks
    local mount_count=$(mount | grep -c "/tmp/shared-mount-" 2>/dev/null || echo 0)
    echo "  Mounted shared disks: $mount_count"
    
    # Check for temporary files
    local temp_files=0
    for pattern in $VM_LOG_PATTERN $VM_ERR_PATTERN $VM_CONFIG_PATTERN $SHARED_DISK_PATTERN; do
        temp_files=$((temp_files + $(ls $pattern 2>/dev/null | wc -l)))
    done
    echo "  Temporary files: $temp_files"
    
    # Check shared directory
    local shared_files=0
    if [ -d "$SHARED_DIR" ]; then
        shared_files=$(find "$SHARED_DIR" -name "*.json" 2>/dev/null | wc -l)
    fi
    echo "  Shared directory files: $shared_files"
    
    # Check VM images
    local vm_images=0
    if [ -d "$VM_IMAGES_DIR" ]; then
        vm_images=$(find "$VM_IMAGES_DIR" -name "*.ext4" -o -name "vmlinux.bin" 2>/dev/null | wc -l)
    fi
    echo "  VM images: $vm_images"
    
    echo ""
}

# Function to display usage information
show_usage() {
    echo "Firecracker VM Teardown Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help           Show this help message"
    echo "  -s, --status         Show current system status"
    echo "  -f, --force          Force cleanup without confirmation"
    echo "  --clean-images       Also remove VM images (kernel, rootfs)"
    echo "  --processes-only     Only kill processes, don't clean files"
    echo "  --files-only         Only clean files, don't kill processes"
    echo ""
    echo "This script will:"
    echo "  1. Kill running Firecracker processes"
    echo "  2. Clean up network interfaces (TAP devices)"
    echo "  3. Unmount shared disk images"
    echo "  4. Remove temporary files and directories"
    echo "  5. Clean up shared directory contents"
    echo "  6. Optionally remove VM images (with --clean-images)"
    echo ""
    echo "Examples:"
    echo "  $0                   # Standard cleanup"
    echo "  $0 --clean-images    # Full cleanup including VM images"
    echo "  $0 --status          # Show current status"
    echo "  $0 --force           # Skip confirmation prompts"
    echo ""
}

# Function to confirm action
confirm_action() {
    if [ "$FORCE_MODE" = "true" ]; then
        return 0
    fi
    
    echo -n "Are you sure you want to proceed? [y/N]: "
    read -r response
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            print_status "Operation cancelled"
            exit 0
            ;;
    esac
}

# Main execution
main() {
    local clean_images=false
    local processes_only=false
    local files_only=false
    local force_mode=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -s|--status)
                show_status
                exit 0
                ;;
            -f|--force)
                force_mode=true
                shift
                ;;
            --clean-images)
                clean_images=true
                shift
                ;;
            --processes-only)
                processes_only=true
                shift
                ;;
            --files-only)
                files_only=true
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # Set global force mode
    FORCE_MODE="$force_mode"
    
    print_status "Starting Firecracker VM teardown..."
    echo ""
    
    # Show current status
    show_status
    
    # Confirm action unless in force mode
    if [ "$force_mode" = "false" ]; then
        confirm_action
    fi
    
    echo ""
    
    # Execute cleanup steps based on options
    if [ "$files_only" = "false" ]; then
        kill_firecracker_processes
        cleanup_network_interfaces
        unmount_shared_disks
    fi
    
    if [ "$processes_only" = "false" ]; then
        cleanup_temp_files
        cleanup_shared_directories
        
        if [ "$clean_images" = "true" ]; then
            remove_vm_images
        else
            cleanup_vm_images
        fi
    fi
    
    echo ""
    print_success "Teardown completed successfully!"
    
    # Show final status
    echo ""
    show_status
    
    if [ "$clean_images" = "false" ] && [ "$processes_only" = "false" ]; then
        print_status "VM images were preserved. Use --clean-images to remove them."
    fi
}

# Run main function
main "$@"
