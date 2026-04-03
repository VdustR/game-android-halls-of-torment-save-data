#!/usr/bin/env python3
"""Halls of Torment save file editor.

Decrypt, modify, and re-encrypt Halls of Torment: Premium (Android) save files.
The save file uses Godot Engine's GDEC format (AES-256-CFB with password-based key).

Usage:
    python hot_save.py decrypt <save.dat> [output.json]
    python hot_save.py encrypt <input.json> [output.dat]
"""

import hashlib
import json
import os
import struct
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Encryption password extracted from Global.gdc (version 1.0.1152).
# May change in future updates — see README.md for extraction method.
PASSWORD = "e4422259-b391-43d3-9284-5f37189420ed"


def get_key():
    """Derive AES-256 key from password using Godot's method.

    Godot's password mode: MD5(password) -> hex string -> ASCII bytes as key.
    """
    return hashlib.md5(PASSWORD.encode()).hexdigest().encode("ascii")


def decrypt(filepath):
    """Decrypt a GDEC save file and return parsed JSON data."""
    with open(filepath, "rb") as f:
        magic = f.read(4)
        if magic != b"GDEC":
            raise ValueError(f"Not a GDEC file (magic: {magic!r})")
        md5_expected = f.read(16)
        data_len = struct.unpack("<Q", f.read(8))[0]
        iv = f.read(16)
        encrypted = f.read()

    dec = Cipher(algorithms.AES(get_key()), modes.CFB(iv)).decryptor()
    decrypted = (dec.update(encrypted) + dec.finalize())[:data_len]

    md5_actual = hashlib.md5(decrypted).digest()
    if md5_actual != md5_expected:
        raise ValueError(
            "MD5 mismatch — wrong password or corrupt file.\n"
            f"  Expected: {md5_expected.hex()}\n"
            f"  Actual:   {md5_actual.hex()}"
        )

    return json.loads(decrypted)


def encrypt(data, filepath):
    """Encrypt JSON data and write as GDEC save file."""
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


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("decrypt", "encrypt"):
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    infile = sys.argv[2]

    if cmd == "decrypt":
        outfile = sys.argv[3] if len(sys.argv) > 3 else infile.replace(".dat", ".json")
        data = decrypt(infile)
        with open(outfile, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Decrypted: {infile} -> {outfile}")

    elif cmd == "encrypt":
        outfile = sys.argv[3] if len(sys.argv) > 3 else infile.replace(".json", ".dat")
        with open(infile) as f:
            data = json.load(f)
        encrypt(data, outfile)
        print(f"Encrypted: {infile} -> {outfile}")


if __name__ == "__main__":
    main()
