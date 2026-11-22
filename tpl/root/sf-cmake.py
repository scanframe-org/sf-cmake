#!/usr/bin/env python3
# coding=utf-8
"""
CMake Library Cloner

Clones the cmake-lib repository into the cmake/lib directory at a specified tag.
"""

from __future__ import annotations
import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
import tarfile

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
parser.add_argument(
	"-e",
	"--extract",
	action="store_true",
	help="Download a tar.gz archive from GitHub and extract it instead of cloning.",
)


# Parse command-line arguments
def parse_args() -> argparse.Namespace:
	return parser.parse_args()


# Main entry point
def main() -> int:
	args = parse_args()

	# Show help if no action flag is provided
	if not args.clone and not args.install and not args.extract:
		parser.print_help()
		return 0

	# Handle --install: clone if needed, then create symlink
	if args.install:
		return do_install(args)

	# Handle --extract: download tar.gz and extract
	if args.extract:
		return do_extract(args)

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


# Download tar.gz from GitHub and extract to target directory
def do_extract(args: argparse.Namespace) -> int:
	"""Download a tar.gz archive from GitHub and extract it into the target directory."""
	if TARGET_DIR.exists():
		print(f"Error: Directory '{TARGET_DIR}' already exists. Aborting.", file=sys.stderr)
		return 1

	# Build the GitHub tar.gz URL from the repo URL and tag
	# REPO_URL is like https://github.com/scanframe-org/sf-cmake.git
	# We need https://github.com/scanframe-org/sf-cmake/archive/refs/tags/{tag}.tar.gz
	repo_url = REPO_URL.rstrip("/").rstrip(".git")
	tar_url = f"{repo_url}/archive/refs/tags/{args.tag}.tar.gz"

	# Create parent directory if needed
	TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)

	# Download the tar.gz file
	tar_path = TARGET_DIR.parent / f"sf-cmake-{args.tag}.tar.gz"
	print(f"Downloading {tar_url}...")
	try:
		urllib.request.urlretrieve(tar_url, str(tar_path))
	except urllib.error.URLError as e:
		print(f"Error: Failed to download tar.gz file.\n{e}", file=sys.stderr)
		return 1

	# Extract the tar.gz file
	print(f"Extracting to {TARGET_DIR.parent}...")
	try:
		with tarfile.open(tar_path, "r:gz") as tf:
			tf.extractall(TARGET_DIR.parent)
	except Exception as e:
		print(f"Error: Failed to extract tar.gz file.\n{e}", file=sys.stderr)
		tar_path.unlink(missing_ok=True)
		return 1

	# Clean up the tar.gz file
	tar_path.unlink()

	# The extracted folder is named sf-cmake-{tag}, rename it to the target name
	extracted_dir = TARGET_DIR.parent / f"sf-cmake-{args.tag}"
	if extracted_dir.exists():
		extracted_dir.rename(TARGET_DIR)
	else:
		print(f"Error: Expected extracted directory '{extracted_dir}' not found.", file=sys.stderr)
		return 1

	print(f"Successfully extracted cmake-lib at tag {args.tag}.")
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
	"""Clone/extract the repository if needed, create a symlink to build.py, and run build.py install --embed."""
	# Clone by default if not already present.
	if args.extract:
		rc = do_extract(args)
	else:
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
		capture_output=False,
		text=True,
	)
	if result.returncode != 0:
		print(f"Error: 'build.py install --embed' failed with code {result.returncode}.", file=sys.stderr)
		return result.returncode
	print("Install completed successfully.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
