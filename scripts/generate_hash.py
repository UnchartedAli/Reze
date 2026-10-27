#!/usr/bin/env python3
"""
Utility script to generate a salted PBKDF2-HMAC-SHA256 password hash for the
Reze Web Panel.

Usage: python3 scripts/generate_hash.py [password]

On PaaS platforms you can skip the hash entirely and set a plain
REZE_PANEL_PASSWORD environment variable instead.

Developer: UnchartedAli · Channel: @yamods
"""

import sys
import getpass
import os

# Add root project path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from reze.web.auth import hash_password

def main():
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("Enter new password for Reze Web Panel: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: Passwords do not match!")
            sys.exit(1)

    if len(password) < 6:
        print("Warning: Password should be at least 6 characters long for security.")

    h = hash_password(password)
    print("\n" + "=" * 60)
    print("Generated PBKDF2 Password Hash for Reze:")
    print("=" * 60)
    print(h)
    print("=" * 60)
    print("\nCopy this value and set it in your .env file as:")
    print(f"REZE_PANEL_PASSWORD_HASH=\"{h}\"\n")

if __name__ == "__main__":
    main()
