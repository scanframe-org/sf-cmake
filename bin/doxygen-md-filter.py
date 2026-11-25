#!/usr/bin/env python3
"""Doxygen INPUT_FILTER for Markdown files.

Applies the 'ref' key of an optional front matter block to the first heading as a '{#ref}' anchor
and writes the filtered text to stdout.
"""
import sys

sys.dont_write_bytecode = True
import os
import re
import hashlib
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

NO_DEBUG = os.environ.get("NO_DOXY_MD_FILTER_DEBUG", "") not in ("", "0")
SCRIPT_NAME = os.path.basename(sys.argv[0])

# A PlantUML fenced block (opening fence through the first closing fence).
_FENCE_RE = re.compile(r"^```plantuml[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)

# A single line inside a fenced block.
_INCLUDE_RE = re.compile(r"^[ \t]*!include[ \t]+(\S+)[ \t]*$", re.MULTILINE)
_START_END_RE = re.compile(r"^[ \t]*@(start|end)uml.*$", re.MULTILINE)

# Markdown image: ![alt](target) or ![alt](target "title")
_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)((?:\s+"[^"]*")?)\)')

# A complete fenced block: up to 3 spaces of indent, a backtick or tilde fence
# of 3+ characters, the body, then a closing fence that starts with the same
# characters as the opening fence (and may be longer).
_FENCE_BLOCK_RE = re.compile(
	r"^(?P<indent>[ ]{0,3})"
	r"(?P<fence>(?P<ch>[`~])(?P=ch){2,})"
	r"(?P<info>[^\n]*)\n"
	r"(?P<body>.*?)"
	r"^[ ]{0,3}(?P=fence)(?P=ch)*[ \t]*$",
	re.MULTILINE | re.DOTALL,
)


def debug(msg):
	"""Writes a message to stderr unless NO_DOXY_MD_FILTER_DEBUG is set."""
	if not NO_DEBUG:
		sys.stderr.write(f"[{SCRIPT_NAME}] {msg}\n")


def usage():
	"""Returns the usage text."""
	return (
		f"Usage: {SCRIPT_NAME} <file.md>\n"
		"Doxygen INPUT_FILTER for Markdown files.\n"
		"Reads the given Markdown file, applies the 'ref:' key of an optional front matter\n"
		"block (---/---) to the first heading as a '{#page}' anchor and writes the result to stdout.\n"
		"Set NO_DOXY_MD_FILTER_DEBUG=1 to disable debug output on stderr.\n"
	)


def embed_include_uml(md_text: str, filepath: str) -> str:
	"""
	Replace `!include <file>.puml` lines inside PlantUML blocks with the
	contents of the referenced file, resolved relative to `work_dir`.

	The block is re-emitted as a single PlantUML fence. The @startuml/@enduml
	markers from included files are removed so they don't nest, and a single
	pair is added around the result if none is present.

	Blocks without `!include` lines, including ordinary embedded diagrams,
	are returned unchanged.
	"""
	work_dir = Path(filepath).parent

	def read_include(name: str) -> str | None:
		path = (work_dir / name).resolve()
		if path.is_file():
			text = path.read_text(encoding="utf-8")
			# Drop start/end markers so included content doesn't nest
			return _START_END_RE.sub("", text).strip("\n")
		debug(f"PlantUML include '{name}' not found in for: {filepath}")
		return ""

	def replace_block(match: re.Match) -> str:
		body = match.group(1)
		if not _INCLUDE_RE.search(body):
			return match.group(0)
		new_body = _INCLUDE_RE.sub(lambda m: read_include(m.group(1)), body)
		new_body = new_body.strip("\n")
		if "@startuml" not in new_body:
			new_body = f"@startuml\n{new_body}\n@enduml"
		return f"```plantuml\n{new_body}\n```"

	return _FENCE_RE.sub(replace_block, md_text)


def split_fenced(text: str):
	"""Yield (segment, is_code) pairs that cover the whole text in order."""
	pos = 0
	for m in _FENCE_BLOCK_RE.finditer(text):
		if m.start() > pos:
			yield text[pos:m.start()], False
		yield m.group(0), True
		pos = m.end()
	if pos < len(text):
		yield text[pos:], False


def replace_relative_images(text: str, filepath: Path, store_dir: Path) -> str:
	"""
	Replace the relative images that exist with a hashed copy in store_dir.
	Image paths are resolved relative to the directory containing filepath.
	"""
	store_dir.mkdir(parents=True, exist_ok=True)
	base = filepath.parent

	def replace(match: re.Match) -> str:
		alt, target, title = match.group(1), match.group(2), match.group(3)
		# Leave URLs, data URIs and absolute paths alone
		if urlparse(target).scheme or Path(target).is_absolute():
			return match.group(0)
		src = (base / unquote(target)).resolve()
		if not src.is_file():
			debug(f"Image '{src}' not found in: {filepath}")
			return match.group(0)
		digest = hashlib.md5(src.read_bytes()).hexdigest()
		filename = f"{digest}{src.suffix}"
		dst = store_dir / filename
		# When the hashed file already exists, don't overwrite it.
		if not dst.exists():
			shutil.copyfile(src, dst)
		return f"![{alt}]({filename}{title})"

	return _IMAGE_RE.sub(replace, text)


def replace_relative_images_outside_code(text: str, filepath: Path, store_dir: Path) -> str:
	"""Apply replace_relative_images to prose only. Fenced code is never modified."""
	return "".join(
		seg if is_code else replace_relative_images(seg, filepath, store_dir)
			for seg, is_code in split_fenced(text))


def markdown_filter(filepath: Path) -> int:
	"""Output the filtered Markdown to stdout."""
	text = open(filepath, encoding="utf-8").read()
	#
	match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
	if match:
		front = match.group(1)
		body = text[match.end():]
		pat = re.compile(r"^(#+ .*?)[ \t]*$", re.MULTILINE)
		ref = re.search(r"^ref:\s*(\S+)\s*$", front, re.MULTILINE)
		if ref:
			value = ref.group(1)
			body = pat.sub(lambda m: f"{m.group(1)}{{#{value}}}", body, count=1)
			debug(f"Found ref '{value}' in: {filepath}")
		text = body
	else:
		debug("Missing 'ref' in front-matter: " + str(filepath))
	# Replace relative images in the text that exist to a hashed version in the binary directory.
	# text = replace_relative_images(text, Path(filepath), Path.cwd())
	text = replace_relative_images_outside_code(text, filepath, Path.cwd())
	# Transform PlantUML includes into embedded ones.
	text = embed_include_uml(text, str(filepath))
	# Write to the output.
	sys.stdout.write(text)
	return 0

def file_list_sort(filepath: Path) -> int:
	"""Write the file list with Markdown files ordered by front-matter rank."""
	paths = filepath.read_text(encoding="utf-8").splitlines()

	def sort_key(name: str) -> tuple[int, int]:
		path = Path(name)
		if path.suffix.lower() != ".md":
			return 1, 0
		with path.open(encoding="utf-8") as markdown_file:
			if markdown_file.readline() != "---\n":
				debug("Missing front-matter in: " + str(path))
				return 0, 999
			front_matter_lines = []
			for line in markdown_file:
				if line in ("---\n", "---"):
					front_matter = "".join(front_matter_lines)
					rank = re.search(r"^rank:\s*(-?\d+)\s*$", front_matter, re.MULTILINE)
					if rank:
						return 0, int(rank.group(1))
					break
				front_matter_lines.append(line)

		debug("Front-matter 'rank' field  not set in: " + str(path))
		return 0, 999

	paths.sort(key=sort_key)
	sys.stdout.write("\n".join(paths))
	if paths:
		sys.stdout.write("\n")
	return 0


def main():
	"""Filters the Markdown file given on the command line to stdout. Returns the exit code."""
	if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
		sys.stderr.write(usage())
		return 0 if len(sys.argv) > 1 else 1
	filepath = Path(sys.argv[1])
	if filepath.suffix.lower() == ".md":
		markdown_filter(filepath)
	elif filepath.suffix.lower() == ".lst":
		file_list_sort(filepath)
	return 0


if __name__ == "__main__":
	try:
		sys.exit(main())
	except Exception as ex:
		sys.stderr.write(f"{SCRIPT_NAME}: error: {ex}\n")
		sys.exit(1)
