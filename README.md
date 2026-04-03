# Halls of Torment — Android Save Data

A comprehensive guide to decrypt, modify, and re-encrypt [**Halls of Torment: Premium**](https://play.google.com/store/apps/details?id=com.halls.of.torment.paid.gp) (Android) save files.

Tested on version **1.0.1152** with DLCs:

- [Supporter Pack](https://store.steampowered.com/app/3386980/Halls_of_Torment__Supporter_Pack/)
- [The Boglands](https://store.steampowered.com/app/3919420/Halls_of_Torment__The_Boglands/) (adds Alchemist, Crone, and The Boglands stage)

Pre-built save files are available on the [Releases](https://github.com/VdustR/game-android-halls-of-torment-save-data/releases) page.

> **Disclaimer**: This guide is for educational and personal use only. Modifying save files may violate the game's terms of service. Use at your own risk.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Environment Setup](#environment-setup)
- [Save File Location](#save-file-location)
- [Save File Format](#save-file-format)
- [Decryption](#decryption)
- [Save File Structure](#save-file-structure)
- [Modification Rules](#modification-rules)
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

Source: [Godot Engine `file_access_encrypted.cpp`](https://github.com/godotengine/godot/blob/4.4-stable/core/io/file_access_encrypted.cpp#L107-L117) (the game uses a v4.6 custom build; the linked 4.4 source has identical encryption logic)

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
   assert zstd_pos != -1, "No zstd data found in .gdc file"
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

### Currency & Resources

| Key | Type | Description | Cap |
|-----|------|-------------|-----|
| `Gold` | float | Gold currency | No hard cap |
| `Shard` | float | Available (unspent) Torment Shards | No cap |
| `NumShards` | float | Total shards ever obtained (historical) | No cap |
| `DuelistCharges` | float | Permanent charges for [Duelist's Spark](https://hot.fandom.com/wiki/Duelist%27s_Spark) necklace. Accumulated by killing Champions (+1), Elites (+2), Bosses (+5), Lords (+15). Bonus = √charges / divisor (diminishing returns). | No cap (√ scaling) |

### Potions & Ingredients

| Key | Type | Description |
|-----|------|-------------|
| `NumAbilityRerollPotions` | float | Ability reroll potions |
| `NumItemChestRerollPotions` | float | Item chest reroll potions |
| `NumTraitBanishPotions` | float | Trait banish potions |
| `NumTraitDoublePotions` | float | Trait double potions |
| `NumTraitMemorizePotions` | float | Trait memorize potions |
| `NumTraitRerollPotions` | float | Trait reroll potions |
| `Ingredients` | array | Crafting material quantities (by index, 15 types) |

> **Warning**: Modifying potion counts or ingredient values may cause the game to reset them to zero on load. Modify at your own risk.

### Blessings

Permanent stat upgrades purchased at the Shrine of Blessings. Max level is **5.0** for all.

```json
{
  "damage": 5.0,
  "damagemagic": 5.0,
  "damagephysical": 5.0,
  "max_health": 5.0,
  "health_regen": 5.0,
  "movement_speed": 5.0,
  "attack_speed": 5.0,
  "crit_chance": 5.0,
  "crit_chance_base": 5.0,
  "crit_bonus": 5.0,
  "multi_strike": 5.0,
  "on_hit_chance": 5.0,
  "blockstrength": 5.0,
  "defense": 5.0,
  "range": 5.0,
  "area": 5.0,
  "duration": 5.0,
  "pickuprange": 5.0,
  "goldgain": 5.0,
  "fire damage": 5.0,
  "frost damage": 5.0,
  "lightning damage": 5.0,
  "abilitychance": 5.0,
  "chestchance": 5.0,
  "revives": 5.0,
  "potionofoblivion": 5.0,
  "potionofmemories": 5.0,
  "reverbanttinkture": 5.0,
  "strongwine": 5.0,
  "agony": 5.0
}
```

### Shard Upgrades

Per-class stat investments via Torment Shards. No hard cap per stat, but very high values (e.g., 1000+) may cause performance issues.

Each shard provides diminishing effect per stat:

| Stat | Per Shard |
|------|-----------|
| Damage | +1% |
| Crit Chance | +0.5% |
| Attack Speed | +0.2% |
| Multistrike | +0.2% |

Known stats: `Area`, `AttackSpeed`, `CritBonus`, `CritChance`, `Damage`, `EffectStrength`, `EmitCount`, `Force`, `HealthRegen`, `MaxHealth`

Known classes (14): `Alchemist`, `Archer`, `Bard`, `Beast Huntress`, `Cleric`, `Crone`, `Exterminator`, `Landsknecht`, `Norseman`, `Sage`, `Shield Maiden`, `Sorceress`, `Swordsman`, `Warlock`

> **Note**: `Shard` should equal `NumShards` minus the sum of all `ShardUpgrades` values.

### Equipment & Items

| Key | Type | Description |
|-----|------|-------------|
| `Equipped` | object | Currently equipped items by slot (`Head`, `Body`, `Feet`, `Gloves`, `Neck`, `Ring_L`, `Ring_R`, `Mark`) |
| `ItemStash` | array | All owned item IDs (string array) |
| `Loadouts` | object | Per-class saved loadouts (class key → slot → item ID) |
| `ItemsInWell` | array | Items placed in the Wellkeeper's well |

Item ID format: `{slot}_{name}_{variant}` (e.g., `ring_iron_boost_rare`)

Rarity tiers in item IDs: (none) = common, `_boost`/`_growth`/etc. = uncommon, `_rare` suffix = very rare (purple)

### Loadout Keys

Loadout keys mostly match lowercase class names, with these exceptions:

| Class | Loadout Key |
|-------|-------------|
| Swordsman | `swordman` (typo in game data) |
| Beast Huntress | `huntress` |
| Shield Maiden | `shieldmaiden` |

### Mark IDs

Class marks use `char_` prefix:

| Class | Mark ID |
|-------|---------|
| Swordsman | `char_swordsman` |
| Archer | `char_archer` |
| Cleric | `char_cleric` |
| Exterminator | `char_exterminator` |
| Landsknecht | `char_landsknecht` |
| Sorceress | `char_sorceress` |
| Norseman | `char_norseman` |
| Shield Maiden | `char_shieldmaiden` |
| Beast Huntress | `char_beasthuntress` |
| Sage | `char_sage` |
| Warlock | `char_warlock` |
| Bard | `char_bard` |
| Alchemist | `char_alchemist` |
| Crone | `char_crone` |

### Progression

| Key | Type | Description |
|-----|------|-------------|
| `Quests` | array | Quest status. Each entry: `{"ID": "q_...", "completed": true/false, "count": float, "hidden": bool}` |
| `Artifacts` | array | Discovered artifact IDs (e.g., `art_stage_traps`) |
| `ActiveArtifacts` | array | Currently active artifact IDs |
| `Unlocked` | array | Unlocked characters, NPCs, and features |

### Metadata

| Key | Type | Description |
|-----|------|-------------|
| `DLCs` | array | Owned DLC identifiers (`dlc_supporter` = Supporter Pack, `dlc_bogsnbooks` = The Boglands) |
| `ProfileVersion` | float | Save format version |
| `WriteCount` | float | Number of times saved |
| `DataDate` | float | Unix timestamp of last save |
| `LevelCount` | float | Total runs played |
| `TrackedQuest` | string | Currently tracked quest ID |
| `LeaderBoardVersion` | float | Leaderboard version |
| `Records` | object | Personal best records |
| `Stats` | object | Lifetime statistics |
| `QuestBoards` | object | Quest board state |

## Modification Rules

### Safe to Modify

| Field | Notes |
|-------|-------|
| `Gold` | No cap. ~120,000 is enough to buy everything; endgame players accumulate millions. |
| `Blessings` | Max 5.0 per blessing. Setting above 5.0 has no additional effect. |
| `ShardUpgrades` | No hard cap. ~200 per stat is a reasonable endgame value. Very high values (1000+) may cause lag. |
| `Shard` / `NumShards` | Keep consistent: `Shard` = `NumShards` - total invested. |
| `DuelistCharges` | No cap. 900 ≈ +100% bonus, 5000 ≈ +236%. Diminishing returns (√ scaling). |
| `ItemStash` | Can add any valid item ID. |
| `Artifacts` | Can add any valid artifact ID. |
| `Quests` | Can mark as completed. |
| `Loadouts` | Can assign items to class loadouts. Use correct loadout keys and mark IDs. |
| `Equipped` | Can set currently worn items. |

### Modify with Caution

| Field | Risk |
|-------|------|
| `NumAbilityRerollPotions` / other potions | **May reset to zero** when the game loads. |
| `Ingredients` | **May reset to zero** when the game loads. |
| `Unlocked` | Adding invalid entries may cause issues. |

### Do Not Modify

| Field | Reason |
|-------|--------|
| `ProfileVersion` | May cause save migration or corruption. |
| `WriteCount` / `DataDate` | Game uses these for cloud sync conflict resolution. |
| `LeaderBoardVersion` | May affect leaderboard eligibility. |

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
adb shell "svc data enable"
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

See [`hot_save.py`](hot_save.py) for a complete CLI tool that handles decrypt and encrypt:

```bash
# Decrypt save file to JSON
python hot_save.py decrypt HoT_progress_profile.dat

# Edit the JSON, then re-encrypt
python hot_save.py encrypt HoT_progress_profile.json
```

## License

[MIT](LICENSE)
