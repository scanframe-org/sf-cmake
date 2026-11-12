#!/bin/bash

# Bailout on first error.
set -e
# Make sure the 'tee pipes' fail correctly. Don't hide errors within pipes.
set -o pipefail

# Get the actual directory of the script where include files are residing.
script_dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
# Include WriteLog function.
source "${script_dir}/inc/Miscellaneous.sh"

## Trap script exit with function.
trap 'ScriptExit "${BASH_SOURCE}" "${BASH_LINENO}" "${BASH_COMMAND}"' EXIT

# Filename wildcards to mach files when filtering using git.
wildcards=("*CMakeLists.txt" "*.cmake")
# Prints the help.
#
function ShowHelp {
	echo "Usage: ${0} [<options>] [<directory/file> ...]
  Options:
  -h, --help        : Show this help.
  -r, --recursive   : Recursively iterate through all subdirectory arguments.
  -g, --git         : Use git-diff to get both staged and unstaged filenames.
  --git-hook        : Use git-diff to get the staged filenames and preferred for a pre-commit git-hook.
  --branch <branch> : Use git-diff using the passed git branch to compare to for files.
  --gitlab-mr       : Use GitLab CI/CD merge-request environment variables for branch and commit SHA to compare for changed files.
  -s, --show        : Show the differences.
  -d, --depth       : Maximum directory depth.
  -f, --format      : Format all found files.
  -q, --quiet       : Quiet, report only when files are not formatted correctly.
  arguments         : Directories to start looking for code-files.

  The is script formats the code using the file '.cmake-format.yaml' found in one of the parent directories.
  When not found it is created in the git top-level (or current) directory using the CLion
  default style (tabs, tab size 2, continuation indent 2). It is not added to git.
  Files from git and given directories are limited to filename wildcards: $(JoinBy ', ' "${wildcards[@]}").

  See for formatting options for configuration file:
     https://cmake-format.readthedocs.io/en/latest/configuration.html
"
}
# Initialize the options with the regular expression.
regex='.*\(/CMakeLists\.txt\|\.cmake\)'
find_options=('-iregex' "${regex}")
# Recursion is disabled by default.
flag_recursive=false
# Format file for real.
flag_format=false
# Enables show diff.
flag_show_diff=false
# Disable being quiet by default.
flag_quiet=false
# Append arguments using the git diff noticed changes of staged and unstaged files.
flag_git_unstaged=false
# Append arguments using the git diff noticed changes of staged files only.
flag_git_staged=false
# Use GitLab CI/CD merge-request environment variables for branch and commit SHA to compare for changed files.
flag_gitlab_mr=false
# File counter of all failed files.
file_fail_count=0
# Max depth is only valid when recursion is enabled.
max_depth=""
# Git branch to compare/diff to.
git_branch=""
# Check if the needed commands are installed.
commands=(
	"colordiff"
	"dos2unix"
	"grep"
	"cmake-format"
)
for command in "${commands[@]}"; do
	if ! command -v "${command}" >/dev/null; then
		WriteLog "Missing command '${command}' for this script!"
		exit 1
	fi
done

# Parse the passed options.
temp=$(getopt -o 'hrgfsqd:' --long 'help,recursive,git,git-hook,branch:,gitlab-mr,format,show,quiet,depth:' -n "$(basename "${0}")" -- "$@")
# shellcheck disable=SC2181
if [[ $? -ne 0 || $# -eq 0 ]]; then
	ShowHelp
	exit 0
fi
eval set -- "$temp"
unset temp
while true; do
	case "$1" in

		-h | --help)
			ShowHelp
			exit 0
			;;

		-r | --recursive)
			flag_recursive=true
			shift 1
			;;

		-g | --git)
			flag_git_staged=true
			flag_git_unstaged=true
			shift 1
			;;

		--git-hook)
			flag_git_staged=true
			flag_git_unstaged=false
			shift 1
			;;

		--branch)
			git_branch="$2"
			shift 2
			;;

		--gitlab-mr)
			flag_gitlab_mr=true
			shift 1
			;;

		-f | --format)
			flag_format=true
			shift 1
			;;

		-s | --show)
			flag_show_diff=true
			shift 1
			;;

		-q | --quiet)
			flag_quiet=true
			shift 1
			;;

		-d | --depth)
			flag_recursive=true
			max_depth="$2"
			shift 2
			continue
			;;

		'--')
			shift
			break
			;;

		*)
			WriteLog "Internal error on argument (${1}) !"
			exit 1
			;;
	esac
done
# Get the arguments in an array.
argument=()
while [[ $# -gt 0 ]] && ! [[ "$1" =~ ^- ]]; do
	argument=("${argument[@]}" "$1")
	shift
done
# Check for recursive operation.
if ${flag_recursive}; then
	# When max directory depth is set.
	find_options=("-maxdepth" "${max_depth:-1}" "${find_options[@]}")
fi

# Find the cfg_file file for cmake-format up the tree.
if ! cfg_file="$("${script_dir}/find-up.sh" --type f ".cmake-format.yaml" 2>/dev/null)" || [[ -z "${cfg_file}" ]]; then

	WriteLog ": cfg_file = ${cfg_file}"
	# Create it in the git top-level directory or the current one when not in a git repository.
	cfg_file="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.cmake-format.yaml"
	WriteLog "# Creating missing format config file: ${cfg_file}"
	# Style matching the CLion defaults: tabs, tab size 2 and continuation indent 2.
	cat >"${cfg_file}" <<'EOF'
# Options affecting listfile parsing.
parse:
  # Specify structure for custom cmake functions.
  additional_commands: {}
  # Override configurations per-command where available.
  override_spec: {}
  # Specify variable tags.
  vartags: []
  # Specify property tags.
  proptags: []

# Options affecting formatting.
format:
  # Disable formatting entirely, making cmake-format a no-op.
  disable: false
  # Maximum line width for formatted CMake files.
  line_width: 120
  # Number of spaces per indentation level.
  tab_size: 2
  # Use tab characters instead of spaces for indentation.
  use_tabchars: true
  # Policy for fractional tab characters: use spaces instead of partial tabs.
  fractional_tab_policy: use-space
  # Maximum number of subgroups before horizontal wrapping.
  max_subgroups_hwrap: 12
  # Maximum number of positional arguments before horizontal wrapping.
  max_pargs_hwrap: 6
  # Maximum number of lines for a cmdline positional group before nesting.
  max_rows_cmdline: 2
  # Separate flow control keywords (if, foreach, while) from their parentheses with a space.
  separate_ctrl_name_with_space: true
  # Do not separate function names from their parentheses.
  separate_fn_name_with_space: false
  # Put the closing parenthesis on its own line.
  dangle_parens: true
  # Align dangling closing parentheses with the command prefix.
  dangle_align: prefix
  # Minimum statement spelling length to force reject nested layouts.
  min_prefix_chars: 4
  # Maximum length of prefix characters for alignment.
  max_prefix_chars: 0
  # Maximum number of lines for horizontal wrapping before rejecting the layout.
  max_lines_hwrap: 2
  # Use Unix-style line endings (LF).
  line_ending: unix
  # Leave CMake command case unchanged.
  command_case: unchanged
  # Leave CMake keyword case unchanged.
  keyword_case: unchanged
  # List of command names which should always be wrapped.
  always_wrap: []
  # Enable lexicographic sorting of argument lists known to be sortable.
  enable_sort: true
  # Allow parser to infer whether an argument list is sortable without annotation.
  autosort: false
  # Require valid layout and exit with error if line width cannot be achieved.
  require_valid_layout: false
  # Dictionary mapping layout nodes to a list of wrap decisions.
  layout_passes: {}

# Options affecting comment reflow and formatting.
markup:
  # Character to use for bulleted lists.
  bullet_char: "*"
  # Character to use as punctuation after numerals in an enumerated list.
  enum_char: "."
  # Preserve the first comment block in each file without reflowing.
  first_comment_is_literal: false
  # Regular expression pattern to match comments that should not be reflowed.
  literal_comment_pattern: null
  # Regular expression to match preformat fences in comments.
  fence_pattern: ^\s*([`~]{3}[`~]*)(.*)$
  # Regular expression to match rulers in comments.
  ruler_pattern: ^\s*[^\w\s]{3}.*[^\w\s]{3}$
  # Pattern to explicitly mark a comment as trailing for the preceding argument.
  explicit_trailing_pattern: "#<"
  # Minimum number of hash characters to preserve in a hash ruler.
  hashruler_min_length: 10
  # Normalize hash rulers by inserting a space and filling the column.
  canonicalize_hashrulers: true
  # Disable comment markup processing to preserve comments as-is.
  enable_markup: false

# Options affecting the linter.
lint:
  # List of lint codes to disable.
  disabled_codes: []
  # Regular expression pattern for valid function names.
  function_pattern: "[0-9a-z_]+"
  # Regular expression pattern for valid macro names.
  macro_pattern: "[0-9A-Z_]+"
  # Regular expression pattern for variables with global (cache) scope.
  global_var_pattern: "[A-Z][0-9A-Z_]+"
  # Regular expression pattern for variables with global scope but internal semantic.
  internal_var_pattern: _[A-Z][0-9A-Z_]+
  # Regular expression pattern for variables with local scope.
  local_var_pattern: "[a-z][a-z0-9_]+"
  # Regular expression pattern for private directory variables.
  private_var_pattern: _[0-9a-z_]+
  # Regular expression pattern for public directory variables.
  public_var_pattern: "[A-Z][0-9A-Z_]+"
  # Regular expression pattern for function/macro arguments and loop variables.
  argument_var_pattern: "[a-z][a-z0-9_]+"
  # Regular expression pattern for keywords used in functions or macros.
  keyword_pattern: "[A-Z][0-9A-Z_]+"
  # Maximum conditionals in a loop before considering it a custom parser.
  max_conditionals_custom_parser: 2
  # Minimum number of newlines between statements.
  min_statement_spacing: 1
  # Maximum number of newlines between statements.
  max_statement_spacing: 2
  # Maximum number of return statements in a function.
  max_returns: 6
  # Maximum number of branches in a function.
  max_branches: 12
  # Maximum number of arguments in a function.
  max_arguments: 5
  # Maximum number of local variables in a function.
  max_localvars: 15
  # Maximum number of statements in a function.
  max_statements: 50

# Options affecting file encoding.
encode:
  # Emit the unicode byte-order mark (BOM) at the start of the file.
  emit_byteorder_mark: false
  # Specify the encoding of the input file.
  input_encoding: utf-8
  # Specify the encoding of the output file.
  output_encoding: utf-8

# Miscellaneous configuration options.
misc:
  # Dictionary containing per-command configuration overrides.
  per_command: {}
EOF
fi
# Report the format configuration file.
if ! "${flag_quiet}"; then
	if [[ "$(uname -o)" == "Cygwin" ]]; then
		cfg_file="$(cygpath -w "${cfg_file}")"
	fi
	WriteLog "# Format config file: ${cfg_file}"
	if ${flag_git_staged}; then
		WriteLog "# Git diff staged files are added."
	fi
	if ${flag_git_unstaged}; then
		WriteLog "# Git diff unstaged files are added."
	fi
	if [[ -n "${git_branch}" ]]; then
		WriteLog "# Git diff files compared to branch '${git_branch}'."
	fi
fi

##
# $1: filename
#
function check_format {
	local file_name="$1"
	# Compare formatted unix file with original one.
	if cmake-format "${file_name}" --config-files "${cfg_file}" | dos2unix | diff -s "${file_name}" - >/dev/null; then
		if ! "${flag_quiet}"; then
			WriteLog "= ${file_name}"
		fi
	else
		# Increment the fail counter.
		((file_fail_count += 1))
		WriteLog "! ${file_name}"
		# Show differences when flag is set.
		if ${flag_show_diff}; then
			cmake-format "${file_name}" --config-files "${cfg_file}" | dos2unix | colordiff "${file_name}" -
			echo "==="
		fi
		# Format the file when the option flag was set.
		if ${flag_format}; then
			# Check for DOS line endings.
			if file "${file_name}" | grep -q 'CRLF'; then
				# And fix it.
				dos2unix "${file_name}" 2>/dev/null || exit 1
			fi
			# Format CMake using the style config file.
			cmake-format --config-files "${cfg_file}" -i "${file_name}" || exit 1
		fi
	fi
}

arguments=()
# Get the relative start directory which must exist otherwise show help and bailout.
for arg in "${argument[@]}"; do
	if ! realpath --relative-to="$(pwd)" -e "${arg}" >/dev/null; then
		WriteLog "Given argument '${arg}' is not relative to current working directory!"
		exit 1
	else
		arguments+=("${arg}")
	fi
done
# Check if git diff branch detected changes are to be added.
if [[ -n "${git_branch}" ]] || ${flag_git_staged} || ${flag_git_unstaged}; then
	# Iterate through all changed CMake files.
	while IFS= read -rd $'\n' line; do
		arguments+=("$line")
	done < <(
		{
			[[ -n "${git_branch}" ]] && git diff "${git_branch}" --name-only --diff-filter=ACMR "${wildcards[@]}"
			${flag_git_staged} && git diff --cached --name-only --diff-filter=ACMR "${wildcards[@]}"
			${flag_git_unstaged} && git diff --name-only --diff-filter=ACMR "${wildcards[@]}"
		} | sort --unique
	)
fi

# Check if git merge request info it to be used.
if ${flag_gitlab_mr}; then
	# List of needed merge request variables.
	merge_vars=(
		CI_MERGE_REQUEST_TARGET_BRANCH_NAME
		CI_MERGE_REQUEST_DIFF_BASE_SHA
	)
	# Iterate over the variable-names and check the existence of them.
	for var in "${merge_vars[@]}"; do
		if [[ -z "${!var}" ]]; then
			WriteLog "Required GitLab merge request variable '$var' is not set!"
			exit 1
		fi
	done
	# Fetch a shallow the target branch for merging.
	git fetch --depth 1 origin "${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}"
	# Iterate through all changed CMake files.
	while IFS= read -rd $'\n' line; do
		arguments+=("$line")
	done < <(git diff "${CI_MERGE_REQUEST_DIFF_BASE_SHA}" --name-only --diff-filter=ACMR "${wildcards[@]}")
fi

# Add the needed find option to separate the each entry.
find_options+=("-print0")
# Iterate through all arguments directories and/or files.
for argument in "${arguments[@]}"; do
	# When the argument is a directory.
	if [[ -d "${argument}" ]]; then
		if ! "${flag_quiet}"; then
			WriteLog "# Entering directory: ${argument}"
		fi
		while read -rd $'\0' fn; do
			check_format "${fn}"
		done < <(find "${argument}" "${find_options[@]}")
	# When the argument is a file.
	elif [[ -f "${argument}" ]]; then
		check_format "${argument}"
	else
		WriteLog "# Ignoring non-existing entry: ${argument}"
	fi
done

# When incorrect formatted files were found.
if [[ "${file_fail_count}" -gt 0 ]]; then
	WriteLog "Total of (${file_fail_count}) files were incorrectly cmake-formatted.
Run command '${0}' with option '--format' to auto fix these files."
	# Signal failure.
	exit 1
fi
