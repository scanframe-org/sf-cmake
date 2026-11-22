#!/usr/bin/env python3
# coding=utf-8
"""
CMake Library Cloner

Clones the cmake-lib repository into the cmake/lib directory at a specified tag.
"""

from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

# Default repository URL and tag
REPO_URL = "https://github.com/scanframe-org/sf-cmake.git"
DEFAULT_TAG = "latest"
TARGET_DIR = Path("cmake/lib")

# Parser instance for reuse
parser = argparse.ArgumentParser(
	description="Clone the cmake-lib repository at a specific tag."
)
parser.add_argument(
	"-c",
	"--clone",
	action="store_true",
	help="Clone the repository. Without this flag, help is shown.",
)
parser.add_argument(
	"-i",
	"--install",
	action="store_true",
	help="Clone the repository if not already present and create a symlink to build.py.",
)
parser.add_argument(
	"-t",
	"--tag",
	default=DEFAULT_TAG,
	help=f"Repository tag to clone (default: {DEFAULT_TAG}).",
)


# Parse command-line arguments
def parse_args() -> argparse.Namespace:
	return parser.parse_args()


# Main entry point
def main() -> int:
	args = parse_args()

	# Show help if neither --clone nor --install flag is provided
	if not args.clone and not args.install:
		parser.print_help()
		return 0

	# Handle --install: clone if needed, then create symlink
	if args.install:
		return do_install(args)

	# Handle --clone: abort if target already exists
	if TARGET_DIR.exists():
		print(f"Error: Directory '{TARGET_DIR}' already exists. Aborting.", file=sys.stderr)
		return 1

	# Create parent directory if needed
	TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)

	# Clone the repository at the specified tag
	print(f"Cloning {REPO_URL} at tag {args.tag} into {TARGET_DIR}...")
	result = subprocess.run(
		["git", "clone", "--branch", args.tag, "--single-branch", REPO_URL, str(TARGET_DIR)],
		capture_output=True,
		text=True,
	)

	if result.returncode != 0:
		print(f"Error: git clone failed.\n{result.stderr}", file=sys.stderr)
		return result.returncode

	print(f"Successfully cloned cmake-lib at tag {args.tag}.")
	return 0


# Clone the repository if not already present
def do_clone(args: argparse.Namespace) -> int:
	"""Clone the repository if the target directory does not yet exist."""
	if TARGET_DIR.exists():
		print(f"Directory '{TARGET_DIR}' already exists, skipping clone.")
		return 0

	# Create parent directory if needed
	TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)

	# Clone the repository at the specified tag
	print(f"Cloning {REPO_URL} at tag {args.tag} into {TARGET_DIR}...")
	result = subprocess.run(
		["git", "clone", "--branch", args.tag, "--single-branch", REPO_URL, str(TARGET_DIR)],
		capture_output=True,
		text=True,
	)

	if result.returncode != 0:
		print(f"Error: git clone failed.\n{result.stderr}", file=sys.stderr)
		return result.returncode

	print(f"Successfully cloned cmake-lib at tag {args.tag}.")
	return 0


# Create symlink to build.py in project root
def do_create_symlink() -> int:
	"""Create a symlink from the project root to cmake/lib/bin/build.py.

	If the symlink already exists and points to the correct target, treat it as success.
	"""
	build_py_target = TARGET_DIR / "bin" / "build.py"
	symlink_path = Path("build.py")

	if not build_py_target.exists():
		print(f"Error: Target '{build_py_target}' does not exist. Cannot create symlink.", file=sys.stderr)
		return 1

	# Check if symlink already exists and points to the correct target
	if symlink_path.is_symlink():
		try:
			if symlink_path.resolve() == build_py_target.resolve():
				print(f"Symlink 'build.py' already exists and is valid.")
				return 0
		except OSError:
			pass

	# Remove existing symlink or file if present
	if symlink_path.exists() or symlink_path.is_symlink():
		symlink_path.unlink()

	symlink_path.symlink_to(build_py_target)
	print(f"Created symlink 'build.py' -> '{build_py_target}'.")
	return 0


# Handle --install option
def do_install(args: argparse.Namespace) -> int:
	"""Clone the repository if needed, create a symlink to build.py, and run build.py install --embed."""
	# Clone if not already present
	rc = do_clone(args)
	if rc != 0:
		return rc
	# Create symlink to build.py
	rc = do_create_symlink()
	if rc != 0:
		return rc
	# Run build.py install --embed
	print("Running 'build.py project --embed'...")
	result = subprocess.run(
		[sys.executable, "build.py", "project", "--embed"],
		capture_output=True,
		text=True,
	)
	if result.stdout:
		print(result.stdout, end="")
	if result.stderr:
		print(result.stderr, end="", file=sys.stderr)
	if result.returncode != 0:
		print(f"Error: 'build.py install --embed' failed with code {result.returncode}.", file=sys.stderr)
		return result.returncode
	print("Install completed successfully.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
