# Halls of Torment — Save File Decryption & Modification Guide

A comprehensive guide to decrypt, modify, and re-encrypt **Halls of Torment: Premium** (Android) save files.

> **Disclaimer**: This guide is for educational and personal use only. Modifying save files may violate the game's terms of service. Use at your own risk.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Environment Setup](#environment-setup)
- [Save File Location](#save-file-location)
- [Save File Format](#save-file-format)
- [Decryption](#decryption)
- [Save File Structure](#save-file-structure)
- [Modification](#modification)
- [Re-encryption](#re-encryption)
- [Pushing Back to Device](#pushing-back-to-device)
- [Cloud Sync Considerations](#cloud-sync-considerations)
- [Script](#script)

## Overview

Halls of Torment: Premium is built with **Godot Engine 4.6** (`custom_build`). The save file uses Godot's built-in `FileAccessEncrypted` with password-based encryption (`save_encrypted_pass`).

Key facts:

- **Save format**: Godot GDEC (AES-256-CFB)
- **Encryption password**: Stored as a UUID string constant in compiled GDScript bytecode (`Global.gdc`)
- **Save content**: JSON
- **Anti-tamper**: The APK uses **pairip** protection, which blocks runtime instrumentation (e.g., Frida attach). However, this does not affect static analysis or save file manipulation.

## Prerequisites

- **Rooted Android device or emulator** (required to access `/data/data/`)
- **ADB** with root shell access
- **Python 3** with:
  - `cryptography` — AES encryption/decryption
  - `zstandard` — GDScript bytecode decompression (only needed for key extraction)

```bash
pip install cryptography zstandard
```

## Environment Setup

### Using Android Emulator with Magisk

If you don't have a rooted device, use an Android Studio AVD:

1. **Create AVD** with `google_apis_playstore` system image (API 34 recommended):

   ```bash
   sdkmanager "system-images;android-34;google_apis_playstore;arm64-v8a"
   avdmanager create avd \
     --name "Game_Research" \
     --package "system-images;android-34;google_apis_playstore;arm64-v8a" \
     --device "pixel_7"
   ```

2. **Launch** with writable system:

   ```bash
   emulator -avd Game_Research -writable-system -no-snapshot-load
   ```

3. **Root with Magisk** using [rootAVD](https://gitlab.com/newbit/rootAVD):

   ```bash
   git clone https://gitlab.com/newbit/rootAVD.git
   cd rootAVD
   ./rootAVD.sh system-images/android-34/google_apis_playstore/arm64-v8a/ramdisk.img
   ```

4. After reboot, open Magisk app → **Superuser** tab → enable toggle for `[SharedUID] Shell`

5. Verify root:

   ```bash
   adb shell "su -c 'id'"
   # uid=0(root) gid=0(root) ...
   ```

## Save File Location

```
/data/data/com.halls.of.torment.paid.gp/files/HoT_progress_profile.dat
```

Other related files:

| File | Description |
|------|-------------|
| `files/settings.json` | Game settings (volume, controls, etc.) — **not encrypted** |
| `files/HoT_progress_profile.dat` | Main save file — **encrypted** |

## Save File Format

The save file uses Godot's `GDEC` format (Godot 4.4+):

```
Offset  Size  Description
------  ----  -----------
0x00    4     Magic: "GDEC" (0x47 0x44 0x45 0x43)
0x04    16    MD5 hash of decrypted plaintext
0x14    8     Data length (uint64 LE) — original unpadded size
0x1C    16    IV (Initialization Vector) for AES-CFB
0x2C    ...   Encrypted data (AES-256-CFB, padded to 16-byte boundary)
```

### Key Derivation (Password Mode)

Godot's `open_and_parse_password()` derives the AES key as follows:

```
password_string
  → MD5 hash → hex string (32 ASCII chars)
  → use ASCII bytes as 32-byte AES-256 key
```

For example, if the password is `"hello"`:

```
MD5("hello") = "5d41402abc4b2a76b9719d911017c592"
AES key = b"5d41402abc4b2a76b9719d911017c592" (32 bytes of ASCII)
```

Source: [Godot Engine `file_access_encrypted.cpp`](https://github.com/godotengine/godot/blob/4.4-stable/core/io/file_access_encrypted.cpp#L107-L117)

### Encryption Password

The encryption password is a UUID constant embedded in the compiled GDScript bytecode (`Global.gdc` inside the APK's asset pack).

To extract it yourself:

1. Pull the APK split containing assets:

   ```bash
   adb shell "pm path com.halls.of.torment.paid.gp"
   # Find split_assetPackInstallTime.apk
   ```

2. Extract and decompress the GDScript bytecode:

   ```python
   import zstandard

   with open("Global.gdc", "rb") as f:
       data = f.read()

   zstd_pos = data.find(b'\x28\xb5\x2f\xfd')  # zstd magic
   compressed = data[zstd_pos:]
   decompressed = zstandard.ZstdDecompressor().decompress(
       compressed, max_output_size=2*1024*1024
   )
   ```

3. Extract strings and look for a UUID pattern (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) adjacent to `HoT_progress_profile.dat`.

The password for version **1.0.1152**: **`e4422259-b391-43d3-9284-5f37189420ed`**

> This password is hardcoded in `Global.gdc` as a string constant adjacent to `HoT_progress_profile.dat`. It is unlikely to change often (doing so would break existing saves without migration), but it may change in future updates. Use the extraction method above to find the current password if decryption fails.

## Decryption

```python
import struct, hashlib, json
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PASSWORD = "e4422259-b391-43d3-9284-5f37189420ed"

def decrypt_save(filepath):
    with open(filepath, "rb") as f:
        magic = f.read(4)
        assert magic == b"GDEC", f"Not a GDEC file: {magic}"
        md5_expected = f.read(16)
        data_len = struct.unpack("<Q", f.read(8))[0]
        iv = f.read(16)
        encrypted = f.read()

    key = hashlib.md5(PASSWORD.encode()).hexdigest().encode("ascii")

    dec = Cipher(algorithms.AES(key), modes.CFB(iv)).decryptor()
    decrypted = (dec.update(encrypted) + dec.finalize())[:data_len]

    md5_actual = hashlib.md5(decrypted).digest()
    assert md5_actual == md5_expected, "MD5 mismatch — wrong password or corrupt file"

    return json.loads(decrypted)
```

## Save File Structure

The decrypted content is JSON. Top-level keys:

| Key | Type | Description |
|-----|------|-------------|
| `Gold` | float | Gold currency |
| `Shard` | float | Available (unspent) shards |
| `NumShards` | float | Total shards ever obtained |
| `ShardUpgrades` | object | Per-class shard investments (class → stat → amount) |
| `Blessings` | object | Blessing levels (stat name → level, max 5.0) |
| `Equipped` | object | Currently equipped items by slot |
| `ItemStash` | array | All owned items |
| `Unlocked` | array | Unlocked characters, NPCs, and features |
| `Quests` | object | Quest completion status |
| `QuestBoards` | object | Quest board state |
| `Records` | object | Personal best records |
| `Stats` | object | Lifetime statistics |
| `Artifacts` | array | All discovered artifacts |
| `ActiveArtifacts` | array | Currently active artifacts |
| `DLCs` | array | Owned DLC identifiers |
| `Loadouts` | object | Saved loadout configurations |
| `Ingredients` | array | Crafting material quantities (by index) |
| `DuelistCharges` | float | Duelist charges count |
| `NumAbilityRerollPotions` | float | Ability reroll potions |
| `NumItemChestRerollPotions` | float | Item chest reroll potions |
| `NumTraitBanishPotions` | float | Trait banish potions |
| `NumTraitDoublePotions` | float | Trait double potions |
| `NumTraitMemorizePotions` | float | Trait memorize potions |
| `NumTraitRerollPotions` | float | Trait reroll potions |
| `ProfileVersion` | float | Save format version |
| `WriteCount` | float | Number of times saved |
| `DataDate` | float | Unix timestamp of last save |
| `LevelCount` | float | Total runs played |
| `TrackedQuest` | string | Currently tracked quest ID |
| `LeaderBoardVersion` | float | Leaderboard version |

### ShardUpgrades Structure

```json
{
  "Swordsman": {
    "Damage": 100.0,
    "AttackSpeed": 50.0,
    "CritChance": 50.0
  },
  "Archer": {
    "Damage": 80.0,
    "EmitCount": 30.0
  }
}
```

Known stats: `Area`, `AttackSpeed`, `CritBonus`, `CritChance`, `Damage`, `EffectStrength`, `EmitCount`, `Force`, `HealthRegen`, `MaxHealth`

Known classes: `Alchemist`, `Archer`, `Bard`, `Beast Huntress`, `Cleric`, `Exterminator`, `Landsknecht`, `Norseman`, `Sage`, `Shield Maiden`, `Sorceress`, `Swordsman`, `Warlock`

### Blessings Structure

```json
{
  "damage": 5.0,
  "max_health": 5.0,
  "revives": 2.0,
  "potionofoblivion": 4.0
}
```

Max level is `5.0` for all blessings.

## Modification

Edit the JSON as needed. Common modifications:

```python
# Gold
data["Gold"] = 99999999.0

# Shards
data["Shard"] = 10000.0
data["NumShards"] = 10000.0

# Max all blessings
for k in data["Blessings"]:
    data["Blessings"][k] = 5.0

# All potions to 99
for k in ["NumAbilityRerollPotions", "NumItemChestRerollPotions",
          "NumTraitBanishPotions", "NumTraitDoublePotions",
          "NumTraitMemorizePotions", "NumTraitRerollPotions"]:
    data[k] = 99.0

# All ingredients to 99
data["Ingredients"] = [99.0] * len(data["Ingredients"])

# Max shard upgrades for all classes
ALL_STATS = ["Area", "AttackSpeed", "CritBonus", "CritChance", "Damage",
             "EffectStrength", "EmitCount", "Force", "HealthRegen", "MaxHealth"]
for cls in data["ShardUpgrades"]:
    if cls == "":
        continue
    for stat in ALL_STATS:
        data["ShardUpgrades"][cls][stat] = 1000.0
```

## Re-encryption

```python
import os

def encrypt_save(data, output_path):
    key = hashlib.md5(PASSWORD.encode()).hexdigest().encode("ascii")
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    iv = os.urandom(16)

    # Pad to 16-byte boundary
    pad_len = len(raw)
    if pad_len % 16:
        pad_len += 16 - (pad_len % 16)
    padded = raw + b"\x00" * (pad_len - len(raw))

    # Encrypt
    enc = Cipher(algorithms.AES(key), modes.CFB(iv)).encryptor()
    encrypted = enc.update(padded) + enc.finalize()

    # Write GDEC file
    with open(output_path, "wb") as f:
        f.write(b"GDEC")
        f.write(hashlib.md5(raw).digest())
        f.write(struct.pack("<Q", len(raw)))
        f.write(iv)
        f.write(encrypted)
```

## Pushing Back to Device

```bash
# 1. Stop the game
adb shell "am force-stop com.halls.of.torment.paid.gp"

# 2. Disable network (prevent cloud sync from overwriting changes)
adb shell "svc wifi disable"
adb shell "svc data disable"

# 3. Push modified save
adb push modified_save.dat /data/local/tmp/HoT_progress_profile.dat
adb shell "su -c '\
  cp /data/local/tmp/HoT_progress_profile.dat \
     /data/data/com.halls.of.torment.paid.gp/files/HoT_progress_profile.dat && \
  chown u0_a193:u0_a193 \
     /data/data/com.halls.of.torment.paid.gp/files/HoT_progress_profile.dat && \
  chmod 600 \
     /data/data/com.halls.of.torment.paid.gp/files/HoT_progress_profile.dat'"

# 4. Launch game (offline)
adb shell "am start -n com.halls.of.torment.paid.gp/com.godot.game.GodotAppLauncher"

# 5. Verify changes in-game, then re-enable network
adb shell "svc wifi enable"
```

> **Note**: The UID (`u0_a193`) may vary per installation. Check with:
>
> ```bash
> adb shell "su -c 'stat /data/data/com.halls.of.torment.paid.gp/files/'"
> ```

## Cloud Sync Considerations

The game syncs saves via **Google Play Games**. If the network is active when the game launches, the cloud save may overwrite local changes.

**Workflow**:

1. Disable network **before** pushing the modified save
2. Launch game offline and verify changes
3. Re-enable network — the game should detect the local save is newer and upload it

If the game prompts for conflict resolution, choose **"Use local save"** or **"Upload"**.

## Script

A complete decrypt → modify → re-encrypt script:

```python
#!/usr/bin/env python3
"""Halls of Torment save file editor."""

import hashlib
import json
import os
import struct
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PASSWORD = "e4422259-b391-43d3-9284-5f37189420ed"


def get_key():
    return hashlib.md5(PASSWORD.encode()).hexdigest().encode("ascii")


def decrypt(filepath):
    with open(filepath, "rb") as f:
        magic = f.read(4)
        assert magic == b"GDEC", f"Not a GDEC file: {magic}"
        md5_expected = f.read(16)
        data_len = struct.unpack("<Q", f.read(8))[0]
        iv = f.read(16)
        encrypted = f.read()

    dec = Cipher(algorithms.AES(get_key()), modes.CFB(iv)).decryptor()
    decrypted = (dec.update(encrypted) + dec.finalize())[:data_len]

    assert hashlib.md5(decrypted).digest() == md5_expected, "MD5 mismatch"
    return json.loads(decrypted)


def encrypt(data, filepath):
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    iv = os.urandom(16)
    pad_len = len(raw) + ((16 - len(raw) % 16) if len(raw) % 16 else 0)
    padded = raw + b"\x00" * (pad_len - len(raw))

    enc = Cipher(algorithms.AES(get_key()), modes.CFB(iv)).encryptor()
    encrypted = enc.update(padded) + enc.finalize()

    with open(filepath, "wb") as f:
        f.write(b"GDEC")
        f.write(hashlib.md5(raw).digest())
        f.write(struct.pack("<Q", len(raw)))
        f.write(iv)
        f.write(encrypted)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python hot_save.py decrypt <save.dat> [output.json]")
        print("  python hot_save.py encrypt <input.json> [output.dat]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "decrypt":
        infile = sys.argv[2]
        outfile = sys.argv[3] if len(sys.argv) > 3 else infile.replace(".dat", ".json")
        data = decrypt(infile)
        with open(outfile, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Decrypted: {infile} -> {outfile}")

    elif cmd == "encrypt":
        infile = sys.argv[2]
        outfile = sys.argv[3] if len(sys.argv) > 3 else infile.replace(".json", ".dat")
        with open(infile) as f:
            data = json.load(f)
        encrypt(data, outfile)
        print(f"Encrypted: {infile} -> {outfile}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
```

## License

[MIT](LICENSE)
