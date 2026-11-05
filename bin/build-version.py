#!/usr/bin/env python3
# coding=utf-8
"""
Version subcommand for build.py.

This subcommand reports or bumps semantic version based on conventional commits.
It analyzes merge commits since the last release tag to determine the next
semantic version and can generate Markdown release notes.
"""

import argparse
import os
import re
import json
import subprocess
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Tuple
import sys

# Use the already-loaded 'build' module from sys.modules to avoid re-importing
# the module-level code (which would create a second config and separate registry).
# When run as './build.py', the module key is '__main__', not 'build'.
build_module = sys.modules.get("build") or sys.modules.get("__main__")
if build_module is None:
	raise ImportError(
		"build-version requires 'build' to be imported first. "
		"This module should only be loaded via _load_subcommand_modules()."
	)
# Fake import to trick IDE.
if build_module is None:
	import build as main
else:
	main = build_module


class SubCommandVersion(main.SubCommand):
	"""Subcommand handler for the 'version' command for repository version reporting and bumping."""

	@dataclass()
	class CommitCacheEntry:
		"""Holds the commit message information."""

		name: str
		date: datetime
		msg: str

		def __init__(self, commit_msg: str):
			"""Constructor taking the formatted message string."""
			lines = commit_msg.split("\n")
			self.name = lines[0]
			self.date = datetime.strptime(lines[1], "%a %b %d %H:%M:%S %Y %z")
			self.msg = "\n".join(lines[2:])

		@staticmethod
		def get_format_string() -> str:
			"""Get the commit message format string."""
			return "%cn\n%cd\n%B"

	_header_regex = re.compile(r"^([a-z_\-]+)(\(([a-z_\-]+)\))?(!)?:\s(.*)$")
	_increment_order = {"none": 0, "patch": 1, "minor": 2, "major": 3}
	# Holds the type map from ini config file.
	_type_map: dict[str, tuple[str, str]] = {}
	# Cache for commit message retrieval.
	_cache_get_cmt_msg: dict[str, CommitCacheEntry] = {}
	# Cache for the git-describe-exact tag retrieval.
	_cache_git_describe_exact: dict[str, str] = {}
	# Module directory to work on.
	_module_dir: str = "."

	def __init__(self):
		super().__init__("version", ["v"])
		# Read the type map from the ini config file.
		for key, value in main.get_config_section("config-ver-type-map", fail=True).items():
			self._type_map[key] = (*value.split(',', 1),)

	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		self.parser = subparsers.add_parser(self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Report or bump semantic version based on conventional commits.")
		self.parser.epilog = f"""
examples:

  {self.script} version info
  {self.script} version bump -V
  {self.script} version bump --msg-file version-bump.msgs.json
  {self.script} version bump --module cmake/lib info -ad
"""
		if self.parser is None:
			raise ValueError("Parser cannot be None")
		return self.parser

	def options(self, parser: argparse.ArgumentParser):
		"""Adds options to the version subcommand."""
		super().options(parser)
		parser.add_argument("-V", "--verbose", action="store_true", help="Output extra processing information.")
		parser.add_argument("-m", "--module", type=str, metavar="<module>", help="Submodule directory to work on.")
		parser.add_argument("-c", "--commit", type=str, metavar="<hash/tag>",
			help="Commit hash to tag as new version (defaults to last commit/HEAD when omitted).")
		parser.add_argument("-a", "--all", action="store_true",
			help="Use all commits and not only merge commits in the process.")
		parser.add_argument("-s", "--select", action="store_true",
			help="Interactively select the target commit since last release tag (respecting merges flag).")
		parser.add_argument("--msg-file", type=str, metavar="<file>",
			help="JSON file containing replacement messages for commit hashes (for debugging).")
		parser.add_argument("-l", "--long", action="store_true",
			help="Use long (full) git hashes; default prints short hashes.")
		parser.add_argument("action", nargs="?", choices=["info", "bump", "msg"],
			help="""
info: Report repository version information on the merge commits.
bump: Generate release notes from the last or given commit hash.
msg: Combine all commit messages into a single file.""")
		parser.epilog = """

message header format:
  <type>(<scope>)!: <short summary>
  │       │      │      └─⫸ Summary in an imperative mood.
  │       │      └─⫸ Optional exclamation mark '!' indicating a breaking change.
  │       └─⫸ Commit Scope: common|compiler|config|cmake|changelog|docs-infra|pack|iface|etc...
  └─⫸ Commit Type: build|ci|chore|docs|feat|fix|perf|refactor|style|test|revert

type to change map:
"""
		for key, value in self._type_map.items():
			parser.epilog += f"  {key} {' ' * (10 - len(key))}{value[0]} {' ' * (8 - len(value[0]))}{value[1]}\n"
		parser.epilog += f"""
examples:
  Report versioning information using the last commit to determine the new version:
    ./{self.script} {self.command} info
  Report versioning information using a by a dialog selected commit:
    ./{self.script} {self.command} info -s
  Create Markdown release-notes in 'doc/release' directory for specified hash or tag:
    ./{self.script} {self.command} bump -c b8d37e2
    ./{self.script} {self.command} bump -c v0.1.0-rc.5
"""
		return parser

	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str] | None) -> int:
		"""Handles the version reporting/bumping."""
		super().handle(args, args_left, args_right)
		if args.module:
			self._module_dir = args.module
		merges_only = not args.all
		main.logger.info(f"# Commits processed: {"Merges only" if merges_only else "All"}")
		if args.select:
			commit_hash = self.select_commit(merges_only)
		elif args.commit:
			# Convert the short or tag to a full commit hash.
			commit_hash = self.git(["rev-parse", args.commit], check=True)
		else:
			commit_hash = self.git(["rev-parse", "--verify", "HEAD"], check=True)
		git_top_level = self.git(["rev-parse", "--show-toplevel"], check=True)
		cur_ver_tag, tag_found = self.get_latest_non_rc_tag()
		tag_annotation = self.get_tag_annotation(cur_ver_tag) if tag_found else ""
		msg_overrides = self.load_message_overrides(args.msg_file)
		long_hash = args.long
		if args.action == "info":
			self.report_version_tags(git_top_level, cur_ver_tag, tag_found, commit_hash, merges_only, msg_overrides,
				tag_annotation, long_hash=long_hash)
			self.bump_version(info_only=True, cur_ver_tag=cur_ver_tag, commit_hash=commit_hash, merges_only=merges_only,
				verbose=args.verbose, tag_found=tag_found, overrides=msg_overrides, git_top_level=git_top_level)
		elif args.action == "bump":
			self.bump_version(info_only=False, cur_ver_tag=cur_ver_tag, commit_hash=commit_hash, merges_only=merges_only,
				verbose=args.verbose, tag_found=tag_found, overrides=msg_overrides, git_top_level=git_top_level)
		elif args.action == "msg":
			self.combine_commit_messages(cur_ver_tag, commit_hash, merges_only, tag_found, msg_overrides,
				git_top_level)
		else:
			main.logger.info("! Missing version command.")
			return 1
		return 0

	@staticmethod
	def escape_markdown(text: str | None) -> str:
		"""Escapes basic Markdown characters."""
		if text is None:
			return ""
		escaped = text
		replacements = {
			"\\": "&#92;",
			"`": "&#96;",
			"*": "&#42;",
			"#": "&#35;",
			"[": "&#91;",
			"]": "&#93;",
		}
		for src, dst in replacements.items():
			escaped = escaped.replace(src, dst)
		return escaped

	# noinspection PyMethodMayBeStatic
	def git(self, args: List[str], check: bool = False) -> str:
		"""Runs git command and returns stdout as string."""
		result = main.run_command(["git", "-C", self._module_dir] + args, capture_output=True, check=check,
			dbg_mode=main.DebugMode.SILENT)
		return result.stdout.decode("utf-8").strip()

	def git_lines(self, args: List[str], check: bool = False) -> List[str]:
		"""Runs git and returns non-empty lines."""
		return [ln for ln in self.git(args, check=check).splitlines() if ln.strip()]

	# noinspection PyMethodMayBeStatic
	def git_describe_exact(self, commit_hash: str) -> str:
		"""Returns exact matching tag or '...' when none."""
		if commit_hash in self._cache_git_describe_exact:
			return self._cache_git_describe_exact[commit_hash]
		result = main.run_command(["git", "describe", "--exact-match", commit_hash], capture_output=True, check=False,
			dbg_mode=main.DebugMode.SILENT)
		result = result.stdout.decode("utf-8").strip() if result.returncode == 0 else "..."
		self._cache_git_describe_exact[commit_hash] = result
		return result

	def get_latest_non_rc_tag(self) -> Tuple[str, bool]:
		"""Returns the latest non-RC tag and flag indicating existence."""
		tags = [tag for tag in self.git_lines(["tag", "--list", "--format", "%(tag)"], check=False)
			if re.match(r"^v\d+\.\d+\.\d+$", tag)]
		if not tags:
			return "v0.0.0", False
		tags.sort(key=lambda t: tuple(int(x) for x in t[1:].split(".")), reverse=True)
		return tags[0], True

	# noinspection PyMethodMayBeStatic
	def get_tag_annotation(self, tag: str) -> str:
		"""Returns annotation text for tag."""
		result = main.run_command(["git", "cat-file", "tag", tag], capture_output=True, check=False,
			dbg_mode=main.DebugMode.SILENT)
		if result.returncode != 0:
			return ""
		raw = result.stdout.decode("utf-8", errors="ignore")
		parts = raw.split("\n\n", 1)
		return parts[1].strip() if len(parts) == 2 else ""

	# noinspection PyMethodMayBeStatic
	def get_git_tag_version(self) -> Tuple[str, str, str, str]:
		"""Returns tuple (version, rc, commits, hash) parsed from git describe information."""
		result = main.run_command(["git", "-C", self._module_dir, "describe", "--dirty", "--match", "v*.*.*"],
			capture_output=True, check=False, dbg_mode=main.DebugMode.SILENT)
		desc = result.stdout.decode("utf-8").strip()
		match = re.match(
			r"^v(?P<ver>[0-9]+\.[0-9]+\.[0-9]+)(-rc\.?(?P<rc>[0-9]+))?(-((?P<commits>[0-9]+)?(-(?P<hash>[a-z0-9]+))?)?)?(-dirty)?$",
			desc)
		if not match:
			return "0.0.0", "", "", ""
		return match.group("ver") or "0.0.0", match.group("rc") or "", match.group("commits") or "", match.group(
			"hash") or ""

	@staticmethod
	def git_tag_version_string(version_info: Tuple[str, str, str, str]) -> str:
		"""Formats the git describe tuple into a version string."""
		version, rc, commits, _ = version_info
		result = version
		if rc:
			result += f"~rc{rc}"
		if commits:
			result += f"+{commits}"
		return result

	# noinspection PyMethodMayBeStatic
	def load_message_overrides(self, msg_file: str | None) -> Dict[str, str]:
		"""Loads message overrides from JSON or shell-format file."""
		if msg_file is None:
			json_default = os.path.join(main.RUN_DIR, ".version-bump.json")
			if os.path.exists(json_default):
				msg_file = json_default
			else:
				return {}
		if not os.path.exists(msg_file):
			main.logger.warning(f": Message file '{msg_file}' not found, ignoring.")
			return {}
		with open(msg_file, "r", encoding="utf-8") as fh:
			data = json.load(fh)
		if isinstance(data, dict):
			return {k: str(v) for k, v in data.items()}
		main.logger.warning(f": Message file '{msg_file}' has unsupported JSON structure, ignoring.")
		return {}

	# noinspection PyMethodMayBeStatic
	def get_commit_message(self, commit_hash: str, overrides: Dict[str, str]) -> CommitCacheEntry:
		"""Returns commit message with overrides applied."""
		# Check the cache for the entry.
		if commit_hash in self._cache_get_cmt_msg:
			return self._cache_get_cmt_msg[commit_hash]
		#  Get the formated message string.
		result = main.run_command(
			["git", "-C", self._module_dir, "show", "--no-patch", f"--format={self.CommitCacheEntry.get_format_string()}",
				commit_hash],
			capture_output=True,
			check=False, dbg_mode=main.DebugMode.SILENT)
		result = result.stdout.decode("utf-8", errors="ignore").strip()
		entry = self.CommitCacheEntry(result)
		# When this commit msg is overridden, assign the message text.
		if commit_hash in overrides:
			entry.msg = overrides[commit_hash]
		# Cache the entry.
		self._cache_get_cmt_msg[commit_hash] = entry
		return entry

	# noinspection PyMethodMayBeStatic
	def collect_commits(self, cur_ver_tag: str, commit_hash: str, merges_only: bool, tag_found: bool) -> List[str]:
		"""Collects commits between tag and commit hash (or from root when no tag)."""
		cmd = ["git", "-C", self._module_dir, "log"]
		if merges_only:
			cmd.append("--merges")
		cmd += ["--pretty=format:%H"]
		cmd.append(f"{cur_ver_tag}^..{commit_hash}" if tag_found else commit_hash)
		result = main.run_command(cmd, capture_output=True, check=False, dbg_mode=main.DebugMode.SILENT)
		if result.returncode != 0 and not result.stdout:
			return []
		return [ln for ln in result.stdout.decode("utf-8").splitlines() if ln.strip()]

	def combine_commit_messages(self, cur_ver_tag: str, commit_hash: str, merges_only: bool, tag_found: bool,
		overrides: dict[str, str], git_top_level: str) -> None:
		"""Combines all commit messages into a single file, sorted by commit type."""
		commit_hashes = self.collect_commits(cur_ver_tag, commit_hash, merges_only, tag_found)
		type_order = list(self._type_map.keys())
		unknown_pos = len(type_order)
		# Build list of (sort_key, message) tuples for stable sorting by type.
		tagged_messages = []
		for ch in commit_hashes:
			entry = self.get_commit_message(ch, overrides)
			msg_header = entry.msg.split("\n", 1)[0]
			match = self._header_regex.match(msg_header)
			if match:
				msg_type = match.group(1)
				sort_key = type_order.index(msg_type) if msg_type in type_order else unknown_pos
			else:
				sort_key = unknown_pos
			tagged_messages.append((sort_key, entry.msg))
		# Stable sort by type position; within the same type, git log order is preserved.
		tagged_messages.sort(key=lambda item: item[0])
		messages = [msg for _, msg in tagged_messages]
		combined = "\n\n---\n\n".join(messages)
		output_file = os.path.join(git_top_level, "COMMITMSG.md")
		with open(output_file, "w", encoding="utf-8") as fh:
			fh.write(combined)
		main.logger.info(f"# Combined {len(messages)} commit message(s) into {output_file}")

	def calculate_next_for_commit(self, cur_ver_tag: str, commit_hash: str, merges_only: bool, tag_found: bool,
		overrides: dict[str, str]
	) -> tuple[str, str]:
		"""Returns the prospective next version tag if bumped at commit_hash."""
		effect_max = "minor" if not tag_found else "none"
		for commit in self.collect_commits(cur_ver_tag, commit_hash, merges_only, tag_found):
			msg_string = self.get_commit_message(commit, overrides).msg
			if not msg_string:
				continue
			msg_header = msg_string.split("\n", 1)[0]
			match = self._header_regex.match(msg_header)
			if not match:
				continue
			msg_type = match.group(1)
			msg_breaking = match.group(4)
			type_effect = self._type_map.get(msg_type, ("none", ""))[0]
			effect = "major" if msg_breaking else type_effect
			effect_max = self.compare_increments(effect, effect_max)
		if effect_max == "none":
			return cur_ver_tag, effect_max
		base_ver = cur_ver_tag[1:] if cur_ver_tag.startswith("v") else cur_ver_tag
		result = f"v{self.increment_version(base_ver, effect_max)}"
		return result, effect_max

	def select_commit(self, merges_only: bool) -> str:
		"""Prompts the user to select a commit since the last tag."""
		cur_ver_tag, tag_found = self.get_latest_non_rc_tag()
		commits = self.collect_commits(cur_ver_tag, "HEAD", merges_only, tag_found)
		if not commits:
			raise subprocess.CalledProcessError(returncode=1, cmd=["git", "-C", self._module_dir, "log"], output=b"",
				stderr=b"No commits found")
		options = {}
		for commit in commits:
			cmt_msg = self.get_commit_message(commit, {})
			heading = cmt_msg.msg.split("\n", 1)[0].strip()
			display = f"{commit[:7]} | {cmt_msg.date} | {heading}"
			options[commit] = display
		choice = main.ask_selection(options=options, title="Select Commit", caption="Choose commit for version calculation")
		if choice is None:
			raise subprocess.CalledProcessError(returncode=1, cmd=["selection"], output=b"", stderr=b"No commit selected")
		return str(choice)

	@staticmethod
	def compare_increments(effect: str, effect_max: str) -> str:
		"""Returns the maximum increment."""
		return effect if SubCommandVersion._increment_order.get(effect, 0) > SubCommandVersion._increment_order.get(
			effect_max, 0) else effect_max

	@staticmethod
	def increment_version(version: str, effect: str) -> str:
		"""Increments version string based on effect."""
		parts = version.split(".")
		while len(parts) < 3:
			parts.append("0")
		major, minor, patch = [int(x) for x in parts[:3]]
		if effect == "patch":
			patch += 1
		elif effect == "minor":
			minor += 1
			patch = 0
		elif effect == "major":
			major += 1
			minor = 0
			patch = 0
		return f"{major}.{minor}.{patch}"

	def bump_version(self, info_only: bool, cur_ver_tag: str, commit_hash: str, merges_only: bool, verbose: bool,
		tag_found: bool, overrides: Dict[str, str], git_top_level: str
	):
		"""Calculates the next version and optionally writes release notes."""
		effect_max = "minor" if not tag_found else "none"
		md_table_lines: List[str] = ["| # | Type | Effect | Scope | Change |", "|---:|:---|:---|:---|:---|"]
		md_change_lines: List[str] = []
		counter = 0
		commits = self.collect_commits(cur_ver_tag, commit_hash, merges_only, tag_found)
		if verbose:
			main.logger.info(f"\n# Conventional commits from version: {cur_ver_tag} to ({commit_hash})")
		for commit in commits:
			cmt_msg = self.get_commit_message(commit, overrides)
			msg_string = cmt_msg.msg
			if not msg_string:
				continue
			msg_header = msg_string.split("\n", 1)[0]
			match = self._header_regex.match(msg_header)
			if not match:
				if verbose:
					main.logger.info(f"~ Ignoring commit: {commit}")
				continue
			msg_type = match.group(1)
			msg_scope = match.group(3) or ""
			msg_breaking = match.group(4)
			msg_heading = match.group(5)
			msg_body = msg_string.split("\n", 1)[1] if "\n" in msg_string else ""
			type_effect = self._type_map.get(msg_type, ("none", ""))[0]
			effect = "major" if msg_breaking else type_effect
			effect_max = self.compare_increments(effect, effect_max)
			if verbose:
				main.logger.info(f"= Accepting commit: {commit}")
				main.logger.info(
					f"Heading\t{msg_heading}\nType\t{msg_type}\nScope\t{msg_scope}\nBreak\t[{msg_breaking}]\nVersion Effect\t{effect}")
				if msg_body.strip():
					main.logger.info(msg_body)
			if not info_only:
				counter += 1
				md_table_lines.append(
					f"| **{counter}** | {self._type_map.get(msg_type, ('', ''))[1]} | {effect} | {msg_scope} | {msg_heading} |")
				md_change_lines.append(
					f"#### {counter}) {self._type_map.get(msg_type, ('', ''))[1]}: {self.escape_markdown(msg_heading)}\n\n{msg_body}\n\n---\n")

		main.logger.info("\n# Version Bump")
		if effect_max == "none":
			main.logger.info(": Changes maximum effect (none) do not bump the version.")
			return
		base_ver = cur_ver_tag[1:] if cur_ver_tag.startswith("v") else cur_ver_tag
		next_ver_tag = f"v{self.increment_version(base_ver, effect_max)}"
		main.logger.info(f"Current ver/tag  : {cur_ver_tag}")
		main.logger.info(f"Max-effect       : {effect_max}")
		main.logger.info(f"Upto commit      : {commit_hash}")
		main.logger.info(f"Next version/tag : {next_ver_tag}")

		if not info_only:
			notes_dir = os.path.join(git_top_level, "doc", "release")
			os.makedirs(notes_dir, exist_ok=True)
			md_file = os.path.join(notes_dir, f"notes-{next_ver_tag}.md")
			with open(md_file, "w", encoding="utf-8") as fh:
				fh.write(f"# Release-notes Version {next_ver_tag}\n\n")
				fh.write(f"## Changelist since version {cur_ver_tag}\n\n")
				fh.write("\n".join(md_table_lines))
				fh.write("\n\n### Changes\n")
				fh.write("\n".join(md_change_lines))
			main.logger.info(f"- Release notes written to {md_file}")

	def report_version_tags(self, git_top_level: str, cur_ver_tag: str, tag_found: bool, commit_hash: str,
		merges_only: bool, overrides: Dict[str, str], tag_annotation: str, long_hash: bool = False
	):
		"""Reports the versions, the annotated tags, and the commit ranges."""

		def fmt_hash(h: str) -> str:
			"""Formats the given hash to a character short one taking the first 7 characters."""
			return h if long_hash else h[:7]

		hash_w = 40 if long_hash else 8
		main.logger.info("\n# Top level directory")
		main.logger.info(git_top_level)

		main.logger.info("\n# Current versions")
		main.logger.info(f"Package (Git) : {self.git_tag_version_string(self.get_git_tag_version())}")
		main.logger.info(f'Last non-rc   : {cur_ver_tag} "{tag_annotation}"')
		if not tag_found:
			main.logger.info(f": No current git version tag was found using '{cur_ver_tag}'.")

		main.logger.info("\n# Annotated version-tags")
		main.logger.info(f"~Tag{'':<11} | Hash{'':<{hash_w - 4}} | Time       | Annotation")
		for line in reversed(self.git_lines(["tag", "--list", "--format", "%(tag)\t%(object)\t%(subject)"], check=False)):
			tag, obj, subject = (line.split("\t", 2) + ["", "", ""])[:3]
			if not re.match(r"^v\d+\.\d+\.\d+(-rc\.\d+)?$", tag):
				continue
			cmt_msg = self.get_commit_message(fmt_hash(obj), {})
			main.logger.info(f"{tag:<15} | {fmt_hash(obj):<{hash_w}} | {cmt_msg.date.date()} | \"{subject}\"")

		if False:
			main.logger.info("\n# All merge commits")
			main.logger.info(f"~Tag{'':<11} | Hash{'':<{hash_w - 4}} | Time       | Bump Version  | Commit heading")
			for commit in self.git_lines(["log", "--merges", "--pretty=format:%H"], check=False):
				tag = self.git_describe_exact(commit)
				cmt_msg = self.get_commit_message(commit, overrides)
				heading = (cmt_msg.msg.split("\n", 1)[0]).strip()
				next_ver, effect = self.calculate_next_for_commit(cur_ver_tag, commit, merges_only=True, tag_found=tag_found,
					overrides=overrides)
				main.logger.info(
					f"{tag:<15} | {fmt_hash(commit):<{hash_w}} | {cmt_msg.date.date()} | {next_ver:<10}{effect[:3]} | {heading}")

		main.logger.info(f"\n# Commits since version: {cur_ver_tag} upto '{commit_hash}'")
		main.logger.info(f"~Tag{'':<11} | Hash{'':<{hash_w - 4}} | Time       | Bump Version   | Commit heading")
		commits = self.collect_commits(cur_ver_tag, commit_hash, merges_only, tag_found)
		for commit in commits:
			tag = self.git_describe_exact(commit)
			cmt_msg = self.get_commit_message(commit, overrides)
			heading = (cmt_msg.msg.split("\n", 1)[0]).strip()
			next_ver, effect = self.calculate_next_for_commit(cur_ver_tag, commit, merges_only=False, tag_found=tag_found,
				overrides=overrides)
			main.logger.info(
				f"{tag:<15} | {fmt_hash(commit):<{hash_w}} | {cmt_msg.date.date()} | {next_ver:<10} {effect[:3]} | {heading}")


# Register the subcommand when the module is imported
SubCommandVersion().register()
