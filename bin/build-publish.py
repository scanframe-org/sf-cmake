#!/usr/bin/env python3
# coding=utf-8
"""
Publish subcommand for build.py.

This subcommand uploads files to a Sonatype Nexus repository depending on their
extension, supporting APT, RAW, and Exchange repositories with various
configuration options.
"""

import argparse
import os
import sys
import glob
import fnmatch
import http.client
from typing import List, Dict, Any
from pathlib import Path
from urllib.parse import quote

# Use the already-loaded 'build' module from sys.modules to avoid re-importing
# the module-level code (which would create a second config and separate registry).
# When run as './build.py', the module key is '__main__', not 'build'.
build_module = sys.modules.get("build") or sys.modules.get("__main__")
if build_module is None:
	raise ImportError(
		"build-publish requires 'build' to be imported first. "
		"This module should only be loaded via _load_subcommand_modules()."
	)
# Fake import to trick IDE.
if build_module is None:
	import build as main
else:
	main = build_module


class SubCommandPublish(main.SubCommand):
	"""Subcommand handler for the 'publish' command."""

	def __init__(self):
		super().__init__("publish", ["u"])

	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		self.parser = subparsers.add_parser(self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Uploads files to a Sonatype Nexus repository depending on their extension.")
		self.parser.epilog = f"""
examples:

  Upload packages to Nexus:
    {self.script} {self.command} bin/pkg/*.deb bin/pkg/*.zip
    {self.script} u -a staging -s dist/staging bin/pkg/*.deb
  File starting with '-':
    {self.script} {self.command} -- -help-file.zip
  Using internal globbing:
    {self.script} {self.command} "bin/pkg/*.deb"
  Upload files to exchange directory:
    {self.script} {self.command} -x "gitlab-ci/shared/devops/pipeline/123" bin/gcov/report.*
  Download files from exchange directory:
    {self.script} {self.command} -x "gitlab-ci/shared/devops/pipeline/123" -l bin/gcov report.xml report.txt
  Dry-run upload:
    {self.script} {self.command} -d bin/pkg/*.deb

  Template ini-file for '.nexus-credentials.ini':

[nexus-credentials]
NEXUS_USER=your-username
NEXUS_PASSWORD=your-password
NEXUS_SERVER_URL=https://nexus.example.com
NEXUS_RAW_REPO=shared
NEXUS_EXCHANGE_REPO=exchange

[nexus-develop]
__inherit__=nexus-credentials
NEXUS_APT_REPO=develop
NEXUS_RAW_SUBDIR=dist/develop
NEXUS_WINGET_REFRESH=winget/develop/admin/refresh

[nexus-staging]
__inherit__=nexus-credentials
NEXUS_APT_REPO=staging
NEXUS_RAW_SUBDIR=dist/staging
NEXUS_WINGET_REFRESH=winget/staging/admin/refresh

[nexus-stable]
__inherit__=nexus-credentials
NEXUS_APT_REPO=stable
NEXUS_RAW_SUBDIR=dist/stable
NEXUS_WINGET_REFRESH=winget/stable/admin/refresh
"""
		if self.parser is None:
			raise ValueError("Parser cannot be None")
		return self.parser

	def options(self, parser: argparse.ArgumentParser):
		"""Adds options to the given parser for the publish command."""
		super().options(parser)
		parser.add_argument("-e", "--exch-repo", type=str, metavar="<repo>",
			help="Sets or overrules variable 'NEXUS_EXCHANGE_REPO' as the exchange-repository.")
		parser.add_argument("-a", "--apt-repo", type=str, metavar="<repo>",
			help="Sets or overrules variable 'NEXUS_APT_REPO' as the apt-repository name.")
		parser.add_argument("-r", "--raw-repo", type=str, metavar="<repo>",
			help="Sets or overrules variable 'NEXUS_RAW_REPO' as the raw-repository name.")
		parser.add_argument("-s", "--raw-sub", type=str, metavar="<subdir>",
			help="Sets or overrules variable 'NEXUS_RAW_SUBDIR' as the subdirectory.")
		parser.add_argument("-S", "--section", type=str, default="develop", metavar="<section>",
			help="Sets the configuration section name (default: 'develop').")
		parser.add_argument("--server-url", type=str, metavar="<url>",
			help="Sets or overrules variable 'NEXUS_SERVER_URL'.")
		parser.add_argument("--user", type=str, metavar="<user>",
			help="Sets or overrules variable 'NEXUS_USER'.")
		parser.add_argument("--password", type=str, metavar="<password>",
			help="Sets or overrules variable 'NEXUS_PASSWORD'.")
		parser.add_argument("-V", "--verbose", action="store_true",
			help="Enables verbose output for upload requests.")
		parser.add_argument("-x", "--exchange", type=str, metavar="<exchange-dir>",
			help="Sets the exchange sub-directory in the repository up- and download (--local).")
		parser.add_argument("-l", "--local", type=str, metavar="<local-dir>",
			help="Sets the exchange local-directory in the exchange repository (only with --exchange).")
		parser.add_argument("files", nargs="*", metavar="<file>",
			help="Files to upload to Nexus repository (use '--' before filenames starting with '-').")
		return parser

	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str] | None) -> int:
		"""
		Handles the 'publish' command execution.
		:return: Exit code.
		"""
		super().handle(args, args_left, args_right)
		# Check for impossible use of standalone argument '--local'.
		if args.local and not args.exchange:
			raise RuntimeError("Option '--local' requires '--exchange' to be specified!")
		# Combine files parsed as positional arguments and arguments after '--'
		raw_files: List[str] = (args.files or []) + (args_right or [])
		# Check if files were passed when uploading (not downloading via --local).
		if not args.local and not raw_files:
			main.logger.error("! No files to upload!")
			self.print_help()
			return 1
		# Get the config section name and check its existence.
		section_name: str = "nexus-" + args.section
		if not main.CONFIG.has_section(section_name):
			main.logger.info(f"# No Nexus configuration: {section_name}")
		# The section is allowed not to exist and do not fail.
		merged = main.get_merged_config_section(section_name, fail=False)
		# Resolve all variables with precedence: CLI arg -> Environment (RUN_ENV) -> INI Config
		nexus_user: str = args.user or main.RUN_ENV.get("NEXUS_USER") or merged.get("NEXUS_USER") or ""
		nexus_password: str = args.password or main.RUN_ENV.get("NEXUS_PASSWORD") or merged.get("NEXUS_PASSWORD") or ""
		nexus_server_url: str = args.server_url or main.RUN_ENV.get("NEXUS_SERVER_URL") or merged.get("NEXUS_SERVER_URL") or ""
		nexus_exchange_repo: str = args.exch_repo or main.RUN_ENV.get("NEXUS_EXCHANGE_REPO") or merged.get(
			"NEXUS_EXCHANGE_REPO") or ""
		nexus_apt_repo: str = args.apt_repo or main.RUN_ENV.get("NEXUS_APT_REPO") or merged.get("NEXUS_APT_REPO") or ""
		nexus_raw_repo: str = args.raw_repo or main.RUN_ENV.get("NEXUS_RAW_REPO") or merged.get("NEXUS_RAW_REPO") or ""
		nexus_raw_subdir: str = args.raw_sub or main.RUN_ENV.get("NEXUS_RAW_SUBDIR") or merged.get("NEXUS_RAW_SUBDIR") or ""
		nexus_winget_refresh: str = args.raw_sub or main.RUN_ENV.get("NEXUS_WINGET_REFRESH") or merged.get(
			"NEXUS_WINGET_REFRESH") or ""
		# Report when overruled by command line arguments.
		if args.verbose:
			if args.raw_repo:
				main.logger.info(f"# RAW repository set to '{nexus_raw_repo}'.")
			if args.raw_sub:
				main.logger.info(f"# RAW subdirectory set to '{nexus_raw_subdir}'.")
			if args.apt_repo:
				main.logger.info(f"# APT repository set to '{nexus_apt_repo}'.")
			if args.exch_repo:
				main.logger.info(f"# EXCHANGE repository set to '{nexus_exchange_repo}'.")
			if args.exchange:
				main.logger.info(f"# Exchange directory set to '{args.exchange}'.")
			if args.local:
				main.logger.info(f"# Local directory set to '{args.local}'.")
		# Check existence of required variables.
		cred_vars = {
			"NEXUS_USER": nexus_user,
			"NEXUS_PASSWORD": nexus_password,
			"NEXUS_SERVER_URL": nexus_server_url,
		}
		if args.exchange:
			# Only required if uploading or downloading from exchange repo.
			cred_vars |= {
				"NEXUS_EXCHANGE_REPO": nexus_exchange_repo,
			}
		else:
			# Only required if uploading to at or raw repo.
			cred_vars |= {
				"NEXUS_APT_REPO": nexus_apt_repo,
				"NEXUS_RAW_REPO": nexus_raw_repo,
				"NEXUS_RAW_SUBDIR": nexus_raw_subdir
			}
		# Check on the presence of required variables.
		flag_var = False
		# Flag indicating the Winget definition cache on the Nexus server needs to be refreshed.
		flag_cache_refresh = False
		for var_name, var_val in cred_vars.items():
			if not var_val:
				main.logger.error(
					f"! Required credentials/config variable '{var_name}' "
					f"is not set by credentials file or by parent environment!")
				flag_var = True
		if flag_var:
			self.print_help()
			return 1
		# Handle Exchange Download: --exchange and --local
		if args.exchange and args.local:
			exchange_sub = str(args.exchange).strip('/\\').replace('\\', '/')
			if main.DEBUG_FLAG:
				if raw_files:
					for pattern in raw_files:
						fn = Path(pattern).name
						dest_file = os.path.join(args.local, fn)
						main.logger.info(
							f"~ Not downloading: GET {str(nexus_server_url).rstrip('/')}/repository/"
							f"{quote(str(nexus_exchange_repo), safe='')}/{exchange_sub}/{fn} -> {dest_file}"
						)
				else:
					main.logger.info(f"~ Not downloading all files from exchange '{exchange_sub}' to '{args.local}'")
				return 0
			#
			search_base_url = (
				f"{str(nexus_server_url).rstrip('/')}/service/rest/v1/search"
				f"?repository={quote(str(nexus_exchange_repo), safe='')}"
				f"&group={quote('/' + exchange_sub, safe='/')}"
			)
			token = None
			assets: List[Dict[str, Any]] = []
			while True:
				token_url = search_base_url if not token else f"{search_base_url}&continuationToken={token or ""}"
				status, data = main.query_nexus_search(token_url, nexus_user, nexus_password, verbose=args.verbose)
				if status < 200 or status >= 300 or not isinstance(data, dict):
					main.logger.error(f"! Search failed ({status}) on repository '{nexus_exchange_repo}' group '{exchange_sub}'")
					if isinstance(data, str) and data:
						main.logger.error(data)
					return 1
				for item in data.get("items", []):
					for asset in item.get("assets", []):
						assets.append(asset)
				token = data.get("continuationToken")
				if not token:
					break

			req_base_names = {Path(f).name for f in raw_files} if raw_files else set()
			if req_base_names:
				for asset in assets:
					asset_path = asset.get("path", "")
					fn = Path(asset_path).name
					# if req_base_names and fn not in req_base_names:
					# 	continue
					if any(fnmatch.fnmatch(fn, pat) or fnmatch.fnmatch(asset_path, pat) for pat in req_base_names):
						main.logger.info(f"- Matching file: {fn}")
					else:
						continue
					download_url = asset.get("downloadUrl", "")
					if not download_url:
						continue
					dest_file = os.path.join(args.local, fn)
					main.logger.info(f"- Downloading file: {asset_path} -> {dest_file}")
					status, err = main.download_file_http(download_url, dest_file, nexus_user, nexus_password, verbose=args.verbose)
					if status < 200 or status >= 300:
						main.logger.error(f"! Download failed ({status}) from '{download_url}' to '{dest_file}'")
						if err:
							main.logger.error(err)
						return 1
			return 0

		# Handle Exchange Upload: --exchange without --local
		if args.exchange:
			expanded_files: List[str] = []
			for pattern in raw_files:
				matches = glob.glob(pattern)
				if matches:
					expanded_files.extend(matches)
				else:
					expanded_files.append(pattern)
			for upload_file in expanded_files:
				if not os.path.isfile(upload_file):
					if args.verbose:
						main.logger.info(f"~ File(s) not found for: {upload_file}")
					continue
				exchange_sub = str(args.exchange).strip('/\\').replace('\\', '/')
				exchange_parts = [quote(part, safe="") for part in exchange_sub.split('/') if part]
				exchange_parts.append(quote(Path(upload_file).name, safe=""))
				exchange_target = "/".join(exchange_parts)
				upload_url = (
					f"{str(nexus_server_url).rstrip('/')}/repository/"
					f"{quote(str(nexus_exchange_repo), safe='')}/{exchange_target}"
				)
				main.logger.info(f"- Uploading EXCHANGE repo file: {upload_file}")
				try:
					response_code, output = main.upload_file_http(upload_url, upload_file, nexus_user, nexus_password,
						method="PUT", verbose=args.verbose)
				except (OSError, ValueError, http.client.HTTPException) as ex:
					main.logger.error(f"! Upload failed for file '{upload_file}': {ex}")
					return 1
				if response_code < 200 or response_code >= 300:
					main.logger.error(f"! Upload EXCHANGE package failed ({response_code}) of file: {upload_file}")
					if output:
						main.logger.error(output)
					return 1
			return 0

		# Handle Regular Publish (neither --exchange nor --local)
		expanded_files: List[str] = []
		for pattern in raw_files:
			matches = glob.glob(pattern)
			if matches:
				expanded_files.extend(matches)
			else:
				expanded_files.append(pattern)

		# Iterate over all files
		for upload_file in expanded_files:
			if not os.path.isfile(upload_file):
				if args.verbose:
					main.logger.info(f"~ File(s) not found with: {upload_file}")
				continue

			ext = upload_file.rsplit('.', 1)[-1].lower()
			if ext not in ["deb", "zip", "zip-def", "exe", "gz", "tgz", "bz2", "xz", "7z", "yaml", "yml", "appimage"]:
				main.logger.warning(f"! No upload method for extension '{ext}' file: {upload_file}")
				continue
			try:
				if ext == "deb":
					main.logger.info(f"- Uploading APT repo file: {upload_file} ({self.get_readable_file_size(upload_file)})")
					upload_url = (
						f"{str(nexus_server_url).rstrip('/')}/service/rest/v1/components"
						f"?repository={quote(str(nexus_apt_repo), safe='')}"
					)
					response_code, output = main.upload_file_http(upload_url, upload_file, nexus_user, nexus_password,
						method="POST", multipart_field="apt.asset",
						content_type="application/vnd.debian.binary-package", verbose=args.verbose)
					upload_kind = "APT package"
				else:
					# Trigger a cache refresh for a winget package.
					if ext == "zip-def":
						flag_cache_refresh = True
					main.logger.info(f"~ Uploading RAW repo file: {upload_file} ({self.get_readable_file_size(upload_file)})")
					raw_sub = str(nexus_raw_subdir).strip('/\\').replace('\\', '/')
					raw_parts = [quote(part, safe="") for part in raw_sub.split('/') if part]
					raw_parts.append(quote(Path(upload_file).name, safe=""))
					raw_target = "/".join(raw_parts)
					upload_url = (
						f"{str(nexus_server_url).rstrip('/')}/repository/"
						f"{quote(str(nexus_raw_repo), safe='')}/{raw_target}"
					)
					response_code, output = main.upload_file_http(upload_url, upload_file, nexus_user, nexus_password,
						verbose=args.verbose)
					upload_kind = "RAW package"
			except (OSError, ValueError, http.client.HTTPException) as ex:
				main.logger.error(f"! Upload failed for file '{upload_file}': {ex}")
				return 1
			if response_code < 200 or response_code >= 300:
				main.logger.error(f"! Upload {upload_kind} failed ({response_code}) of file: {upload_file}")
				if output:
					main.logger.error(output)
				return 1
		# Check if the Winget cache is needed to be refreshed and is able to.
		if flag_cache_refresh:
			if nexus_winget_refresh:
				main.logger.info(f"~ Refreshing Winget definition cache.")
				refresh_url = f"{nexus_server_url}/{nexus_winget_refresh}"
				response_code, output = main.post_request_http(url=refresh_url, username=nexus_user, password=nexus_password,
					verbose=args.verbose)
				if response_code < 200 or response_code >= 300:
					main.logger.error(f"! Refreshing Winget definition cache failed ({response_code})")
					if output:
						main.logger.error(output)
					return 1
			else:
				main.logger.error(f": Not refreshing Winget definition cache due to an empty URL.")
		return 0

	@staticmethod
	def get_readable_file_size(filepath):
		"""Returns a human-readable file size."""
		try:
			size_bytes = os.path.getsize(filepath)
		except FileNotFoundError:
			return "File not found"
		for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti']:
			precision: int = 2 if len(unit) != 0 else 0
			if size_bytes < 1024.0:
				return f"{size_bytes:.{precision}f} {unit}B"
			size_bytes /= 1024.0


# Register the subcommand when the module is imported
SubCommandPublish().register()
