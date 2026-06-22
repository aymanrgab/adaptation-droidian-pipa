#!/usr/bin/env python3
"""Map Android logical partitions from super to device-mapper for Droidian."""

import struct, os, sys, subprocess, glob

SECTOR_SIZE = 512
MAGIC_GEOMETRY = 0x414D504C
MAGIC_HEADER = 0x474D504C
NEEDED = ["vendor", "system"]


def find_super():
    for p in ("/dev/disk/by-partlabel/super", "/dev/block/by-partlabel/super",
              "/dev/block/platform/*/by-name/super",
              "/dev/block/bootdevice/by-name/super"):
        for m in glob.glob(p):
            r = os.path.realpath(m)
            if os.path.exists(r):
                return r
    return None


def read_geometry(fd):
    fd.seek(0)
    d = fd.read(4096)
    if len(d) < 52:
        return None
    magic = struct.unpack_from('<I', d, 0)[0]
    if magic != MAGIC_GEOMETRY:
        return None
    return {
        "metadata_max_size": struct.unpack_from('<I', d, 40)[0],
        "metadata_slot_count": struct.unpack_from('<I', d, 44)[0],
        "logical_block_size": struct.unpack_from('<I', d, 48)[0],
    }


def slot_suffix():
    for path in ('/proc/bootconfig', '/proc/cmdline'):
        try:
            with open(path) as f:
                for tok in f.read().split():
                    if 'androidboot.slot_suffix' in tok:
                        s = tok.split('=')[-1].strip('"\'').strip()
                        if s:
                            return s
        except OSError:
            pass
    return '_a'


def read_metadata(fd, offset, size):
    fd.seek(offset)
    raw = fd.read(size)
    if len(raw) < 68:
        return None
    pos = 0
    magic = struct.unpack_from('<I', raw, pos)[0]
    if magic != MAGIC_HEADER:
        return None
    pos += 20
    tables_size = struct.unpack_from('<I', raw, pos)[0]
    pos += 8
    num_parts = struct.unpack_from('<I', raw, pos)[0]
    pos += 4
    part_entry_size = struct.unpack_from('<I', raw, pos)[0]
    pos += 4
    num_extents = struct.unpack_from('<I', raw, pos)[0]
    pos += 4
    ext_entry_size = struct.unpack_from('<I', raw, pos)[0]
    pos += 4
    num_groups = struct.unpack_from('<I', raw, pos)[0]
    pos += 4
    group_entry_size = struct.unpack_from('<I', raw, pos)[0]
    pos += 4
    pos += 8
    pos += 8
    block_size = struct.unpack_from('<I', raw, pos)[0]

    header_size = struct.unpack_from('<I', raw, 12)[0]
    tables_off = offset + header_size

    parts = []
    for i in range(num_parts):
        poff = tables_off + i * part_entry_size
        fd.seek(poff)
        pdata = fd.read(part_entry_size)
        if len(pdata) < 8:
            break
        nsz = struct.unpack_from('<I', pdata, 0)[0]
        name = pdata[4:4 + nsz].split(b'\x00')[0].decode('utf-8', errors='replace')
        name_off = 4 + nsz
        if name_off % 4:
            name_off += 4 - (name_off % 4)
        if name_off + 16 > len(pdata):
            break
        parts.append({
            "name": name,
            "first_extent": struct.unpack_from('<I', pdata, name_off + 4)[0],
            "num_extents": struct.unpack_from('<I', pdata, name_off + 8)[0],
        })

    exts = []
    for i in range(num_extents):
        eoff = tables_off + num_parts * part_entry_size + i * ext_entry_size
        fd.seek(eoff)
        edata = fd.read(ext_entry_size)
        if len(edata) < 32:
            break
        nb, tt, td, ts = struct.unpack_from('<QQQQ', edata, 0)
        exts.append({"num_blocks": nb, "target_type": tt,
                     "target_data": td, "target_source": ts})

    return {"block_size": block_size, "partitions": parts, "extents": exts}


def create_dm(name, super_dev, table_lines):
    subprocess.run(["dmsetup", "remove", name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = subprocess.run(["dmsetup", "create", name],
                       input="\n".join(table_lines).encode(),
                       capture_output=True)
    if r.returncode == 0:
        mapper_path = f"/dev/mapper/{name}"
        print(f"Mapped {mapper_path}")
        for link_dir in ("/dev/disk/by-partlabel", "/dev/block/by-partlabel"):
            link = os.path.join(link_dir, name)
            os.makedirs(link_dir, exist_ok=True)
            if not os.path.exists(link):
                os.symlink(mapper_path, link)
                print(f"  symlink {link} -> {mapper_path}")
        return True
    print(f"Failed /dev/mapper/{name}: {r.stderr.decode().strip()}", file=sys.stderr)
    return False


def main():
    super_dev = find_super()
    if not super_dev:
        print("super partition not found", file=sys.stderr)
        return 1

    super_real = os.path.realpath(super_dev)
    print(f"super: {super_real}")

    with open(super_real, "rb") as fd:
        geo = read_geometry(fd)
        if not geo:
            print("no LP geometry at start of super", file=sys.stderr)
            return 1

        meta_size = geo["metadata_max_size"]
        slot = slot_suffix()
        print(f"slot: {slot}")

        meta = None
        for i in range(geo["metadata_slot_count"]):
            meta = read_metadata(fd, meta_size * i, meta_size)
            if meta:
                print(f"metadata slot {i} valid")
                break
        if not meta:
            print("no valid metadata in any slot", file=sys.stderr)
            return 1

        lb = meta["block_size"]
        for needed in NEEDED:
            part = None
            for candidate in (f"{needed}{slot}", needed):
                for p in meta["partitions"]:
                    if p["name"] == candidate:
                        part = p
                        break
                if part:
                    break

            if not part:
                print(f"{needed}: not found in LP table", file=sys.stderr)
                continue

            if os.path.exists(f"/dev/mapper/{needed}"):
                print(f"{needed}: already mapped")
                continue

            lines = []
            logical_sector = 0
            ok = True
            for ei in range(part["num_extents"]):
                ext = meta["extents"][part["first_extent"] + ei]
                if ext["target_type"] != 0:
                    print(f"{needed}: extent {ei} is not linear, skipping",
                          file=sys.stderr)
                    ok = False
                    break
                if ext["target_source"] != 0:
                    print(f"{needed}: extent {ei} is cross-partition, skipping",
                          file=sys.stderr)
                    ok = False
                    break

                num_sectors = ext["num_blocks"] * lb // SECTOR_SIZE
                lines.append(
                    f"{logical_sector} {num_sectors} linear "
                    f"{super_real} {ext['target_data']}"
                )
                logical_sector += num_sectors

            if ok and lines:
                create_dm(needed, super_real, lines)

    return 0


if __name__ == "__main__":
    sys.exit(main())
