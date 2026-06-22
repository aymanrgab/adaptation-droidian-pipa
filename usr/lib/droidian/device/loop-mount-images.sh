#!/bin/sh
# Loop-mount vendor/odm/product images from /data for Android container.
set -e

IMAGES_DIR="${IMAGES_DIR:-/data}"
PARTS="vendor odm product"

for part in $PARTS; do
    img="$IMAGES_DIR/$part.img"
    [ -f "$img" ] || continue

    # Check if already mounted
    if [ -L "/dev/disk/by-partlabel/$part" ]; then
        existing="$(readlink -f "/dev/disk/by-partlabel/$part")"
        if losetup "$existing" 2>/dev/null | grep -q "$img"; then
            echo "$part: already loop-mounted as $existing"
            continue
        fi
    fi

    # Set up loop device
    loop="$(losetup -f --show "$img")"
    echo "$part: $loop -> $img"

    # Create symlink
    mkdir -p /dev/disk/by-partlabel /dev/block/by-partlabel
    for link_dir in /dev/disk/by-partlabel /dev/block/by-partlabel; do
        ln -sf "$loop" "$link_dir/$part"
    done
done
