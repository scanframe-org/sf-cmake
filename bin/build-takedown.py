#!/usr/bin/env python3
# coding=utf-8
"""
Takedown subcommand for build.py.

This subcommand lists and optionally deletes files from a Sonatype Nexus repository
matching the given wildcards, supporting APT and RAW (winget) repositories.
"""

import argparse
import base64
import ssl
import sys
import fnmatch
import re
import http.client
from typing import List, Dict, Any
from pathlib import Path
from urllib.parse import quote, urlsplit

# Use the already-loaded 'build' module from sys.modules to avoid re-importing
# the module-level code (which would create a second config and separate registry).
# When run as './build.py', the module key is '__main__', not 'build'.
build_module = sys.modules.get("build") or sys.modules.get("__main__")
if build_module is None:
	raise ImportError(
		"build-takedown requires 'build' to be imported first. "
		"This module should only be loaded via _load_subcommand_modules()."
	)
# Fake import to trick IDE.
if build_module is None:
	import build as main
else:
	main = build_module


class SubCommandTakedown(main.SubCommand):
	"""Subcommand handler for the 'takedown' command."""

	def __init__(self):
		super().__init__("takedown", ["td"])

	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		self.parser = subparsers.add_parser(self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Lists and optionally deletes files from a Sonatype Nexus repository.")
		self.parser.epilog = f"""
examples:

  List APT packages matching a wildcard:
    {self.script} {self.command} "*.deb"
    {self.script} td -t apt -a develop "myapp-*"
  List RAW packages matching a wildcard:
    {self.script} td -t raw -r shared -s dist/develop "*.zip"
  Delete matching files:
    {self.script} td -t apt --delete "old-package-*"
  Dry-run (list only, no API calls):
    {self.script} td -d "*.deb"

  Template ini-file for '.nexus-credentials.ini':

[nexus-credentials]
NEXUS_USER=your-username
NEXUS_PASSWORD=your-password
NEXUS_SERVER_URL=https://nexus.example.com
NEXUS_RAW_REPO=shared

[nexus-develop]
__inherit__=nexus-credentials
NEXUS_APT_REPO=develop
NEXUS_RAW_SUBDIR=dist/develop

[nexus-staging]
__inherit__=nexus-credentials
NEXUS_APT_REPO=staging
NEXUS_RAW_SUBDIR=dist/staging

[nexus-stable]
__inherit__=nexus-credentials
NEXUS_APT_REPO=stable
NEXUS_RAW_SUBDIR=dist/stable
"""
		if self.parser is None:
			raise ValueError("Parser cannot be None")
		return self.parser

	def options(self, parser: argparse.ArgumentParser):
		"""Adds options to the given parser for the takedown command."""
		super().options(parser)
		parser.add_argument("-a", "--apt-repo", type=str, metavar="<repo>",
			help="Sets or overrules variable 'NEXUS_APT_REPO' as the apt-repository name.")
		parser.add_argument("-r", "--raw-repo", type=str, metavar="<repo>",
			help="Sets or overrules variable 'NEXUS_RAW_REPO' as the raw-repository name.")
		parser.add_argument("-s", "--raw-sub", type=str, metavar="<subdir>",
			help="Sets or overrules variable 'NEXUS_RAW_SUBDIR' as the subdirectory.")
		parser.add_argument("-S", "--section", type=str, default="develop",
			metavar="<section>", choices=["develop", "staging", "stable"],
			help="Sets the configuration section name (default: 'develop').")
		parser.add_argument("--server-url", type=str, metavar="<url>",
			help="Sets or overrules variable 'NEXUS_SERVER_URL'.")
		parser.add_argument("--user", type=str, metavar="<user>",
			help="Sets or overrules variable 'NEXUS_USER'.")
		parser.add_argument("--password", type=str, metavar="<password>",
			help="Sets or overrules variable 'NEXUS_PASSWORD'.")
		parser.add_argument("-V", "--verbose", action="store_true",
			help="Enables verbose output for requests.")
		parser.add_argument("-t", "--type", type=str, metavar="<type>",
			default="apt", choices=["apt", "raw"],
			help="Sets the type of files to take down (default: 'apt').")
		parser.add_argument("-R", "--regex", action="store_true",
			help="Positional wildcard arguments are now treated as regular expressions.")
		parser.add_argument("--delete", action="store_true",
			help="Actually deletes the files from the Nexus repository instead of only listing.")
		parser.add_argument("wildcards", nargs="*", metavar="<wildcard>",
			help="File name patterns to match for takedown (use '--' before wildcards starting with '-').")
		return parser

	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str] | None) -> int:
		"""
		Handles the 'takedown' command execution.
		:return: Exit code.
		"""
		super().handle(args, args_left, args_right)
		# Get the config section name and check its existence.
		section_name: str = "nexus-" + args.section
		if not main.CONFIG.has_section(section_name):
			main.logger.info(f"# No Nexus configuration: {section_name}")
		# The section is allowed not to exist and do not fail.
		merged = main.get_merged_config_section(section_name, fail=False)
		# Resolve all variables with precedence: CLI arg -> Environment (RUN_ENV) -> INI Config
		nexus_user: str = args.user or main.RUN_ENV.get("NEXUS_USER") or merged.get("NEXUS_USER") or ""
		nexus_password: str = args.password or main.RUN_ENV.get("NEXUS_PASSWORD") or merged.get("NEXUS_PASSWORD") or ""
		nexus_server_url: str = args.server_url or main.RUN_ENV.get("NEXUS_SERVER_URL") or merged.get(
			"NEXUS_SERVER_URL") or ""
		nexus_apt_repo: str = args.apt_repo or main.RUN_ENV.get("NEXUS_APT_REPO") or merged.get("NEXUS_APT_REPO") or ""
		nexus_raw_repo: str = args.raw_repo or main.RUN_ENV.get("NEXUS_RAW_REPO") or merged.get("NEXUS_RAW_REPO") or ""
		nexus_raw_subdir: str = args.raw_sub or main.RUN_ENV.get("NEXUS_RAW_SUBDIR") or merged.get("NEXUS_RAW_SUBDIR") or ""
		# Report when overruled by command line arguments.
		if args.verbose:
			if args.raw_repo:
				main.logger.info(f"# RAW repository set to '{nexus_raw_repo}'.")
			if args.raw_sub:
				main.logger.info(f"# RAW subdirectory set to '{nexus_raw_subdir}'.")
			if args.apt_repo:
				main.logger.info(f"# APT repository set to '{nexus_apt_repo}'.")
		# Check existence of required variables.
		cred_vars = {
			"NEXUS_USER": nexus_user,
			"NEXUS_PASSWORD": nexus_password,
			"NEXUS_SERVER_URL": nexus_server_url,
		}
		# Depending on the type, require the appropriate repository.
		if args.type == "apt":
			cred_vars |= {
				"NEXUS_APT_REPO": nexus_apt_repo,
			}
		else:
			# Type  'raw' uses RAW repository.
			cred_vars |= {
				"NEXUS_RAW_REPO": nexus_raw_repo,
			}
		# Check on the presence of required variables.
		flag_var = False
		for var_name, var_val in cred_vars.items():
			if not var_val:
				main.logger.error(
					f"! Required credentials/config variable '{var_name}' "
					f"is not set by credentials file or by parent environment!")
				flag_var = True
		if flag_var:
			self.print_help()
			return 1
		#
		file_type = args.type
		wildcards = args.wildcards or []
		# Determine which repository to search based on file type.
		if file_type == "apt":
			repo_name = nexus_apt_repo
		else:
			# Type 'raw' uses the RAW repository.
			repo_name = nexus_raw_repo
		# Build the search URL for the Nexus search API.
		# For APT repos we search by repository; for RAW we also filter by group (subdir).
		search_base_url = (
			f"{str(nexus_server_url).rstrip('/')}/service/rest/v1/search"
			f"?repository={quote(str(repo_name), safe='')}"
		)
		if file_type == "raw" and nexus_raw_subdir:
			search_base_url += f"&group={quote('/' + str(nexus_raw_subdir).strip('/\\').replace('\\', '/'), safe='/')}"
		# Collect all components and their assets from the search API (handles pagination).
		# Each item has a 'component' object with an 'id' and an 'assets' array.
		# We need the component ID to delete via the REST API.
		token = None
		components: List[Dict[str, Any]] = []
		while True:
			token_url = search_base_url if not token else f"{search_base_url}&continuationToken={token}"
			status, data = self.query_nexus_search(token_url, nexus_user, nexus_password, verbose=args.verbose)
			if status < 200 or status >= 300 or not isinstance(data, dict):
				main.logger.error(f"! Search failed ({status}) on repository '{repo_name}'")
				if isinstance(data, str) and data:
					main.logger.error(data)
				return 1
			for item in data.get("items", []):
				components.append(item)
			token = data.get("continuationToken")
			if not token:
				break
		if not components:
			main.logger.info("# No files found in repository.")
			return 0
		# Filter components by the provided patterns (match against asset paths).
		matched_components: List[Dict[str, Any]] = []
		for comp in components:
			assets_in_comp = comp.get("assets", [])
			asset_path: str = ""
			for asset in assets_in_comp:
				asset_path = asset.get("path", "")
			asset_name = Path(asset_path).name
			# Check if any pattern matches the file name or full path.
			if args.regex:
				for pattern in wildcards:
					if re.search(pattern, asset_name) or re.search(pattern, asset_path):
						matched_components.append(comp)
						break
			else:
				for pattern in wildcards:
					if fnmatch.fnmatch(asset_name, pattern) or fnmatch.fnmatch(asset_path, pattern):
						matched_components.append(comp)
						break
			continue
		#
		if not matched_components:
			main.logger.info("# No files matched the given wildcards.")
			return 0
		# List the matched files (expand assets within matched components).
		main.logger.info(f"# Found {len(matched_components)} component(s) matching wildcards:")
		for comp in matched_components:
			for asset in comp.get("assets", []):
				asset_path = asset.get("path", "")
				repo = asset.get("repository", repo_name)
				size_str = self.get_readable_file_size(asset.get("fileSize", 0))
				datetime_str = asset.get("lastModified", "")
				main.logger.info(f"  - [{repo}] {datetime_str} {asset_path} ({size_str})")
		# If --delete is not set, stop after listing.
		if not args.delete:
			main.logger.info("# Use --delete to actually remove the files.")
			return 0
		# Delete each matched component using the Nexus REST API.
		main.logger.info(f"# Deleting {len(matched_components)} component(s)...")
		for comp in matched_components:
			component_id = comp.get("id", "")
			if not component_id:
				main.logger.warning(": No component ID — skipping.")
				continue
			comp_path = comp.get("assets", [{}])[0].get("path", "?")
			main.logger.info(f"- Deleting: {comp_path}")
			try:
				response_code, output = self.delete_component(str(nexus_server_url), component_id, nexus_user, nexus_password,
					verbose=args.verbose)
			except (OSError, ValueError, http.client.HTTPException) as ex:
				main.logger.error(f"! Delete failed for '{comp_path}': {ex}")
				return 1
			if response_code < 200 or response_code >= 300:
				main.logger.error(f"! Delete failed ({response_code}) for '{comp_path}'")
				if output:
					main.logger.error(output)
				return 1
			else:
				main.logger.info(f"~ Deleted: {comp_path}")

		main.logger.info(f"# Successfully deleted {len(matched_components)} component(s).")
		return 0

	@staticmethod
	def get_readable_file_size(size_bytes: int) -> str:
		"""Returns a human-readable file size from a byte count."""
		if size_bytes is None or size_bytes < 0:
			return "?B"
		for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti']:
			precision: int = 2 if len(unit) != 0 else 0
			if size_bytes < 1024.0:
				return f"{size_bytes:.{precision}f}{unit}B"
			size_bytes /= 1024.0
		return f"{size_bytes:.2f}PiB"

	@staticmethod
	def query_nexus_search(url: str, username: str, password: str, verbose: bool = False) -> tuple[int, Any]:
		"""Performs an HTTP GET request to Nexus search API and returns parsed JSON data."""
		parsed_url = urlsplit(url)
		if parsed_url.scheme not in ["http", "https"] or not parsed_url.hostname:
			raise ValueError(f"Unsupported or invalid search URL: {url}")
		request_target = parsed_url.path or "/"
		if parsed_url.query:
			request_target += f"?{parsed_url.query}"
		headers = {
			"Authorization": "Basic " + base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii"),
			"Accept": "application/json",
		}
		if main.DEBUG_FLAG:
			main.logger.info(f"~ Not querying: GET {url}")
			return 200, {"items": []}
		if verbose:
			main.logger.info(f"~ Querying: GET {url}")
		connection_class = http.client.HTTPSConnection if parsed_url.scheme == "https" else http.client.HTTPConnection
		connection_args: Dict[str, Any] = {}
		if parsed_url.scheme == "https":
			connection_args["context"] = ssl.create_default_context()
		# noinspection bad-argument-type
		connection = connection_class(parsed_url.hostname, parsed_url.port, **connection_args)
		try:
			connection.request("GET", request_target, headers=headers)
			response = connection.getresponse()
			response_body = response.read().decode("utf-8", errors="replace")
			if verbose:
				main.logger.info(f"~ Nexus response: HTTP {response.status} {response.reason}")
			if response.status < 200 or response.status >= 300:
				return response.status, response_body
			try:
				data = main.json.loads(response_body)
				return response.status, data
			except main.json.JSONDecodeError as ex:
				main.logger.error(f"! Failed to parse JSON response: {ex}")
				return response.status, response_body
		finally:
			connection.close()

	@staticmethod
	def delete_component(server_url: str, component_id: str, username: str, password: str,
		verbose: bool = False) -> tuple[int, str]:
		"""Deletes a component via the Nexus REST API: DELETE /service/rest/v1/components/{id}."""
		base = str(server_url).rstrip("/")
		delete_url = f"{base}/service/rest/v1/components/{quote(component_id, safe='')}"
		parsed_url = urlsplit(delete_url)
		if parsed_url.scheme not in ["http", "https"] or not parsed_url.hostname:
			raise ValueError(f"Unsupported or invalid server URL: {server_url}")
		request_target = parsed_url.path or "/"
		if parsed_url.query:
			request_target += f"?{parsed_url.query}"
		headers = {
			"Authorization": "Basic " + base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii"),
			"Accept": "application/json",
		}
		if main.DEBUG_FLAG:
			main.logger.info(f"~ Not deleting: DELETE {delete_url}")
			return 204, ""
		if verbose:
			main.logger.info(f"~ Deleting: DELETE {delete_url}")
		connection_class = http.client.HTTPSConnection if parsed_url.scheme == "https" else http.client.HTTPConnection
		connection_args: Dict[str, Any] = {}
		if parsed_url.scheme == "https":
			connection_args["context"] = ssl.create_default_context()
		# noinspection bad-argument-type
		connection = connection_class(parsed_url.hostname, parsed_url.port, **connection_args)
		try:
			connection.request("DELETE", request_target, headers=headers)
			response = connection.getresponse()
			response_body = response.read().decode("utf-8", errors="replace")
			if verbose:
				main.logger.info(f"~ Nexus response: HTTP {response.status} {response.reason}")
			return response.status, response_body
		finally:
			connection.close()


# Register the subcommand when the module is imported
SubCommandTakedown().register()
