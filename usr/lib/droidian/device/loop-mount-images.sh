#!/bin/sh
# Loop-mount vendor/odm/product images for Android container.
# Checks /userdata/ and /data/ for .img files.
set -e

for dir in /userdata /data; do
    [ -d "$dir" ] && IMAGES_DIR="$dir" && break
done
: "${IMAGES_DIR:=/userdata}"

# Determine A/B slot suffix from kernel cmdline or bootconfig
slot=""
for src in /proc/bootconfig /proc/cmdline; do
    s="$(grep -o 'androidboot\.slot_suffix[= ].*' "$src" 2>/dev/null | grep -o '[_ab]\+' || true)"
    [ -n "$s" ] && slot="$s" && break
done

PARTS="vendor odm product"

for part in $PARTS; do
    img="$IMAGES_DIR/$part.img"
    [ -f "$img" ] || { echo "$part: $img not found, skipping"; continue; }

    # Check if already loop-mounted
    existing=""
    for d in /dev/disk/by-partlabel /dev/block/by-partlabel; do
        sym="$d/$part"
        [ -L "$sym" ] && existing="$(readlink -f "$sym")" && break
    done

    if [ -n "$existing" ] && losetup "$existing" 2>/dev/null | grep -qF "$img"; then
        echo "$part: already loop-mounted as $existing -> $img"
        continue
    fi

    # Force-unmount and remove stale dynpart device-mapper targets.
    # Does NOT check for /dev/mapper node — the device may exist in the
    # kernel table without a udev node yet.
    kill_dynpart() {
        for dm in "$part" "$part$slot"; do
            for suffix in "" "_a" "_b"; do
                target="dynpart-${dm}${suffix}"
                # Force-unmount anything mounted from this device
                for mp in /vendor /android/vendor /var/lib/lxc/android/rootfs/vendor; do
                    mountpoint -q "$mp" 2>/dev/null && umount -l "$mp" 2>/dev/null || true
                done
                dmsetup remove "$target" 2>/dev/null && echo "$part: removed stale $target" || true
            done
        done
    }

    kill_dynpart

    # Set up loop device
    loop="$(losetup -f --show "$img")"
    echo "$part: $loop -> $img"

    # Kill dynpart again — losetup of large images takes time, dynpart may have appeared
    kill_dynpart

    # Create symlinks (with and without slot suffix for A/B compat)
    mkdir -p /dev/disk/by-partlabel /dev/block/by-partlabel
    for link_dir in /dev/disk/by-partlabel /dev/block/by-partlabel; do
        ln -sf "$loop" "$link_dir/$part"
        [ -n "$slot" ] && ln -sf "$loop" "$link_dir/${part}${slot}"
    done
done
