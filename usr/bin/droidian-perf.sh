#!/bin/bash
# Droidian performance tweaks for Xiaomi Pad 6 (pipa)
# Runs after Android container boots

set -e

# Set GPU frequency to max for smoother UI
if [ -d /sys/class/kgsl/kgsl-3d0 ]; then
    echo "performance" > /sys/class/kgsl/kgsl-3d0/devfreq/governor 2>/dev/null || true
fi

# Let power-profiles-daemon manage CPU governors if active
if ! systemctl is-active -q power-profiles-daemon.service 2>/dev/null; then
    for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo "schedutil" > "$cpu" 2>/dev/null || true
    done
fi

# I/O scheduler for UFS
for iosched in /sys/block/*/queue/scheduler; do
    echo "kyber" > "$iosched" 2>/dev/null || true
done
