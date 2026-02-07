#!/usr/bin/env python3
"""Generate bcrypt password hash for Streamlit Authenticator."""

import getpass
import streamlit_authenticator as stauth


def main():
    print("=" * 60)
    print("Password Hash Generator")
    print("=" * 60)
    print()
    print("This will generate a bcrypt hash for use in auth_config.yaml")
    print()

    # Get password from user
    password = getpass.getpass("Enter password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("ERROR: Passwords don't match!")
        return

    if len(password) < 8:
        print("WARNING: Password is short. Consider using at least 8 characters.")
        proceed = input("Continue anyway? (y/N): ")
        if proceed.lower() != 'y':
            return

    # Generate hash
    print("\nGenerating hash...")
    hashed = stauth.Hasher([password]).generate()

    print("\n" + "=" * 60)
    print("Generated Hash:")
    print("=" * 60)
    print()
    print(hashed[0])
    print()
    print("Copy this hash to your auth_config.yaml file")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
    except ImportError:
        print("ERROR: streamlit-authenticator not installed")
        print("Run: pip install streamlit-authenticator")
