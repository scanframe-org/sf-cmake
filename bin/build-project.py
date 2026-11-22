#!/usr/bin/env python3
# coding=utf-8
"""
Demo subcommand for build.py.

This subcommand serves as an example of how to create a subcommand module
that is dynamically imported by the main build.py script.
"""

import sys
import argparse
import os
import shutil

# Use the already-loaded 'build' module from sys.modules to avoid re-importing
# the module-level code (which would create a second config and separate registry).
# When run as './build.py', the module key is '__main__', not 'build'.
build_module = sys.modules.get("build") or sys.modules.get("__main__")
if build_module is None:
	raise ImportError(
		"build-qtdesign requires 'build' to be imported first. "
		"This module should only be loaded via _load_subcommand_modules()."
	)
# Fake import to trick IDE.
if build_module is None:
	import build as main
else:
	main = build_module


class SubCommandProject(main.SubCommand):
	"""Subcommand handler for the 'demo' command."""

	def __init__(self):
		super().__init__("project")

	def create_parser(self, subparsers):
		"""Create the parser for the demo subcommand."""
		self.parser = subparsers.add_parser(
			self.command,
			aliases=self.aliases,
			add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Project subcommand.",
			description="A module for embedding this repository as a helper into an existing project."
		)
		if self.parser is None:
			raise ValueError("Parser cannot be None")
		return self.parser

	def options(self, parser):
		"""Add options to the demo subcommand parser."""
		super().options(parser)
		parser.add_argument("--embed", action="store_true",
			help="Create all symlinks and copy file needed for to fully use this repository.")

	def handle(self, args, args_left, args_right):
		"""Handle the demo subcommand execution."""
		super().handle(args, args_left, args_right)
		#
		if args.embed:
			if not self.embed():
				return 1
		else:
			self.print_help()
		return 0

	@staticmethod
	def embed() -> bool:
		"""
		Creates symlinks and copies files to embed this repository into an existing project or repository.
		"""
		dir_cmake_lib = str(os.path.join(*([main.RUN_DIR] + main.CMAKE_LIB_SUBDIR)))
		dir_tpl = os.path.join(main.RUN_DIR, dir_cmake_lib, "tpl")
		# Template files and their destinations.
		tpl_files = [
			([dir_tpl, "root", "default.clang-format"], [".clang-format"]),
			([dir_tpl, "root", "default.cmake-format.yaml"], [".cmake-format.yaml"]),
			([dir_tpl, "root", "default.gitignore"], [".gitignore"]),
			([dir_tpl, "root", "git-pre-commit-hook.sh"], [".git", "hooks", "pre-commit"]),
			([dir_tpl, "root", "CMakePresets.json"], ["CMakePresets.json"]),
			(["CMakeUserPresets.json"], ["CMakeUserPresets.json"])
		]
		# Iterate through all the files with their final destinations.
		for entry in tpl_files:
			# From the source filepath.
			src_file = os.path.join(*entry[0])
			# Form the actual destination filepath.
			dst_file = os.path.join(main.RUN_DIR, *entry[1])
			# Check if the destination file already exists and skip it if it does.
			if os.path.exists(dst_file):
				main.logger.info(f"# Skipping existing file: {os.path.join(*entry[1])}")
			else:
				main.logger.info(f"# Copying file: {entry[0]} > {os.path.join(*entry[1])}")
				if not main.DEBUG_FLAG:
					# Ignore if the source file does not exist.
					if len(src_file) > 0:
						if os.path.isfile(src_file):
							shutil.copy(src_file, dst_file)
						else:
							main.logger.warning(f": Missing source file: {src_file}")
				else:
					main.logger.debug(f"~ Not copying file '{src_file}'")
		# Assemble the files to be symlinked.
		symlink_files = [
			([dir_tpl, "root", "CMakePresets.json"], ["CMakePresets.json"]),
			([dir_tpl, "root", "doc", "CMakeLists.txt"], ["doc", "CMakeLists.txt"]),
			([dir_cmake_lib, "inc","base-config-presets.json"], ["cmake", "base-config-presets.json"]),
			([dir_cmake_lib, "bin","check-format.sh"], ["check-format.sh"]),
			([dir_cmake_lib, "bin","cmake-format.sh"], ["cmake-format.sh"]),
		]
		# Iterate through all the files with their final destinations.
		for entry in symlink_files:
			# From the source filepath.
			src_file = os.path.join(dir_cmake_lib, *entry[0])
			# Form the actual destination filepath.
			dst_file = os.path.join(main.RUN_DIR, *entry[1])
			# Check if the destination file already exists and skip it if it does.
			if os.path.exists(dst_file):
				main.logger.info(f"# Skipping existing file: {os.path.join(*entry[1])}")
			else:
				main.logger.info(f"# Symlink file: '{entry[0]}' > '{os.path.join(*entry[1])}'.")
				if not main.DEBUG_FLAG:
					# Ignore if the source file does not exist.
					if len(src_file) > 0:
						if os.path.isfile(src_file):
							os.symlink(src_file, dst_file)
						else:
							main.logger.warning(f": Missing source file: {src_file}")
				else:
					main.logger.debug(f"~ Not creating symlink to: {src_file}")
		return True


# Register the subcommand when the module is imported
SubCommandProject().register()
