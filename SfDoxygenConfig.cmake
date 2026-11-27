include(FetchContent)

##!
# Adds a Doxygen documentation target to the project.
# @param _Target Name of the documentation build target.
# @param [BASEDIR] Base directory used to resolve relative paths. Defaults to CMAKE_SOURCE_DIR.
# @param [OUTDIR] Directory where the generated documentation is written. Defaults to 'bin/man'.
# @param [SRCDIR] Source directory used to find documentation directories. Defaults to 'src'.
# @param [DOCDIR] Name of documentation subdirectories to include. Defaults to 'doc'.
# @param [INCLUDE] Relative glob patterns for files to include in the documentation.
# @param [EXCLUDE] Regular expression used to filter files from the documentation.
# @param [MAIN] Main page file relative to the BASEDIR when '*' is passed the main page is auto selected.
# @param [LOGO] Logo file relative to the BASEDIR.
# @param [THEME] Enable the Awesome Doxygen theme.
# @param [TARGETS] Targets to generate the document about.
# @param [PLANTUML] PlantUML version to download, or an empty value to disable PlantUML.
#
function(Sf_AddDoxygenDocument _Target)
	# Location of the doxygen configuration file in the binary directory.
	set(_bin_dir "${CMAKE_BINARY_DIR}/.docs")
	set(_options THEME)
	set(_one_value_args BASEDIR OUTDIR SRCDIR DOCDIR PLANTUML LOGO MAIN)
	set(_multi_value_args INCLUDE EXCLUDE TARGETS)
	# Parse the arguments
	cmake_parse_arguments(PARSE_ARGV 1 _arg "${_options}" "${_one_value_args}" "${_multi_value_args}")
	if (_arg_UNPARSED_ARGUMENTS)
		message(FATAL_ERROR "${CMAKE_CURRENT_FUNCTION}: Unknown arguments: ${_arg_UNPARSED_ARGUMENTS}")
	endif ()
	# Set the default output directory.
	if (NOT DEFINED _arg_BASEDIR)
		set(_arg_BASEDIR "${CMAKE_SOURCE_DIR}")
	endif ()
	if (NOT DEFINED _arg_OUTDIR)
		set(_arg_OUTDIR "bin/man")
	endif ()
	if (NOT IS_ABSOLUTE "${_arg_OUTDIR}")
		string(PREPEND _arg_OUTDIR "${_arg_BASEDIR}/")
	endif ()
	if (NOT DEFINED _arg_SRCDIR)
		set(_arg_SRCDIR "src")
	endif ()
	if (NOT DEFINED _arg_DOCDIR)
		set(_arg_DOCDIR "doc")
	endif ()
	if (NOT DEFINED _arg_MAIN OR _arg_MAIN STREQUAL "")
		set(_arg_MAIN "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/tpl/root/doc/mainpage.md")
	elseif (_arg_MAIN STREQUAL "*")
		message(STATUS "${CMAKE_CURRENT_FUNCTION}: Auto select main page.")
	else ()
		set(_arg_MAIN "${_arg_BASEDIR}/${_arg_MAIN}")
	endif ()
	if (NOT DEFINED _arg_LOGO OR _arg_LOGO STREQUAL "")
		set(_arg_LOGO "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/tpl/root/doc/logo.png")
	endif ()
	set(_list "")
	# Make the relative glob patterns absolute.
	foreach (_entry IN LISTS _arg_INCLUDE)
		string(PREPEND _entry "${_arg_BASEDIR}/")
		list(APPEND _list "${_entry}")
	endforeach ()
	set(_arg_INCLUDE ${_list})
	# Create the binary directory if it does not exist.
	file(MAKE_DIRECTORY "${_bin_dir}")
	# Initialize the list of documents.
	set(_src_list)
	# Get the markdown files in this directory and the cmake library.
	foreach (_entry ${_arg_INCLUDE})
		cmake_path(GET _entry PARENT_PATH _dir)
		# When Dow not allow to recurse into the source directory.
		if (_dir STREQUAL "${CMAKE_SOURCE_DIR}")
			file(GLOB _list RELATIVE "${_bin_dir}" "${_entry}")
		else ()
			file(GLOB_RECURSE _list RELATIVE "${_bin_dir}" ${_entry})
		endif ()
		list(APPEND _src_list ${_list})
	endforeach ()
	list(APPEND _src_list ${_list})
	# Get all 'doc' named subdirectories in the source tree relative to the binary directory
	# where Doxygen is running from where images are possibly accessed.
	Sf_GetNamedSubdirectories(_doc_dirs "${_arg_BASEDIR}/${_arg_SRCDIR}" "${_bin_dir}" "${_arg_DOCDIR}")
	foreach (_dir ${_doc_dirs})
		set(_glob "${_bin_dir}/${_dir}/*.md")
		file(GLOB _list RELATIVE "${_bin_dir}" "${_glob}")
		list(APPEND _src_list ${_list})
	endforeach ()
	# When an exclude pattern is defined, remove the files that match it.
	if (DEFINED _arg_EXCLUDE)
		list(FILTER _src_list INCLUDE REGEX "${_arg_EXCLUDE}")
	endif ()
	# Create a list for sorting.
	list(JOIN _src_list "\n" _list_txt)
	file(WRITE "${_bin_dir}/markdown.lst" "${_list_txt}")
	execute_process(
		COMMAND "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/bin/doxygen-md-filter.py" "${_bin_dir}/markdown.lst"
		WORKING_DIRECTORY "${_bin_dir}"
		OUTPUT_VARIABLE _list_txt
		OUTPUT_STRIP_TRAILING_WHITESPACE
		COMMAND_ERROR_IS_FATAL ANY
	)
	# Create a list from the output again.
	string(REPLACE "\n" ";" _src_list "${_list_txt}")
	# Check for auto select of main page.
	if (_arg_MAIN STREQUAL "*")
		set(_matched "")
		foreach(_entry IN LISTS _src_list)
			string(TOLOWER "${_entry}" _name)
			get_filename_component(_name "${_name}" NAME)
			# Exact matches go first so add with 'PREPEND'.
			if(_name MATCHES "^(index|main|mainpage|main-page|start|startpage|start-page)\\.md$")
				list(PREPEND _matched "${_entry}")
				# Partial matches are ordered by 'rank' anyway so add with 'APPEND'.
			elseif(_name MATCHES ".*(index|main|start).*\\.md$")
				list(APPEND _matched "${_entry}")
			endif()
		endforeach()
		# Just add the source list incase nothing was matched.
		list(APPEND _matched ${_src_list})
		# When a file was matched.
		if (NOT _matched STREQUAL "")
			list(GET _matched 0 _entry)
			get_filename_component(DG_MainPage "${_bin_dir}/${_entry}" ABSOLUTE)
		endif ()
	else ()
		# Set the MarkDown main page when it exists.
		if (EXISTS "${_arg_MAIN}")
			file(RELATIVE_PATH DG_MainPage "${_bin_dir}" "${_arg_MAIN}")
			list(APPEND _src_list "${DG_MainPage}")
		endif ()
	endif ()
	# When no targets are passed use the 'doc' flag to determine the targets to be include.
	if (NOT DEFINED _arg_TARGETS)
		# Retrieve all 'doc;' flagged targets from the global projects.
		Sf_GetTargetsByFlag(_arg_TARGETS "doc")
	endif ()
	foreach (_entry IN LISTS _arg_TARGETS)
		# Exclude fetched targets.
		get_target_property(_source_dir "${_entry}" SOURCE_DIR)
		string(FIND "${_source_dir}" "${FETCHCONTENT_BASE_DIR}" _Pos)
		if (_Pos EQUAL 0)
			message(VERBOSE "Document Target Skipped: ${_entry}")
			continue()
		endif ()
		get_target_property(_type "${_entry}" TYPE)
		# Only use executables and shared or static libraries.
		if (_type STREQUAL "EXECUTABLE" OR _type STREQUAL "SHARED_LIBRARY" OR _type STREQUAL "STATIC_LIBRARY")
			message(VERBOSE "Document Target (${_type}): ${_entry}")
			list(APPEND _doc_targets "${_entry}")
		endif ()
	endforeach ()
	# Get the source files from the the passed document targets.
	Sf_GetSourceFiles(_sources "${_doc_targets}" "${_bin_dir}")
	# Only add files with the '.h' extension.
	list(FILTER _sources INCLUDE REGEX ".*\\.h$")
	# Remove unwanted header file(s) ending on 'Private.h'.
	list(FILTER _sources EXCLUDE REGEX ".*Private\\.h$")
	# Remove unwanted header file(s) ending on '_p.h'.
	list(FILTER _sources EXCLUDE REGEX ".*_p\\.h$")
	# Add the target found sources to the list.
	list(APPEND _src_list ${_sources})
	# Output a list of sources.
	list(JOIN _src_list "\n\t" _files)
	message(VERBOSE "Target Files:\n\t${_files}")
	# Get the actual output directory.
	Sf_GetFilenameComponent(_arg_OUTDIR "${_arg_OUTDIR}" REALPATH)
	# Check if the resulting directory exists.
	if (NOT EXISTS "${_arg_OUTDIR}" OR NOT IS_DIRECTORY "${_arg_OUTDIR}")
		file(MAKE_DIRECTORY "${_arg_OUTDIR}")
		message(NOTICE "${CMAKE_CURRENT_FUNCTION}: Output directory '${_arg_OUTDIR}' does not exist and is created!")
	endif ()
	# Disable TLS check in windows.
	if ("${CMAKE_HOST_SYSTEM_NAME}" STREQUAL "Windows")
		set(_TlsCheck FALSE)
	else ()
		set(_TlsCheck TRUE)
	endif ()
	# Add doxygen project when doxygen executable was found.
	if (NOT DOXYGEN_EXECUTABLE)
		message(WARNING "${CMAKE_CURRENT_FUNCTION}(): Doxygen application was not found!")
		return()
	endif ()
	message(STATUS "Doxygen: ${DOXYGEN_EXECUTABLE}")
	# Check if the version was passed in the optional argument.
	if (NOT DEFINED _arg_PLANTUML)
		# Get the latest release version number from 'https://github.com/plantuml/plantuml/tags' through the API.
		Sf_GetGitHubVersion(_version "plantuml" "plantuml")
		# When found override the default.
		if (_version)
			set(_arg_PLANTUML "${_version}")
		endif ()
	endif ()
	# Check if the version still isn't defined.
	if (NOT DEFINED _arg_PLANTUML)
		# Set default plantuml version to the known latest.
		set(_arg_PLANTUML "1.2025.10")
	endif ()
	# Download only when a version was set.
	if (NOT _arg_PLANTUML STREQUAL "")
		message(STATUS "Doxygen > PlantUML version to download: '${_arg_PLANTUML}'")
		# Check GitHub for latest releases at 'https://github.com/plantuml/plantuml/releases'.
		FetchContent_Declare(
			PlantUmlJar URL "https://github.com/plantuml/plantuml/releases/download/v${_arg_PLANTUML}/plantuml.jar"
			DOWNLOAD_NO_EXTRACT TRUE DOWNLOAD_NO_PROGRESS TRUE TLS_VERIFY ${_TlsCheck}
		)
		# Download it.
		FetchContent_MakeAvailable(PlantUmlJar)
		# Set the variable used in the configuration template.
		set(DG_PlantUmlJar "${plantumljar_SOURCE_DIR}")
	endif ()
	# Just a copy of the current project version and description.
	set(DG_ProjectVersion "${CMAKE_PROJECT_VERSION}")
	set(DG_ProjectDescription "${CMAKE_PROJECT_DESCRIPTION}")
	if (WIN32)
		find_program(
			DOT_EXECUTABLE NAMES dot PATHS "C:/Program Files/Graphviz/bin" "C:/Program Files (x86)/Graphviz/bin"
			"$ENV{ProgramFiles}/Graphviz/bin" "$ENV{ProgramFiles\(x86\)}/Graphviz/bin"
			DOC "Graphviz dot executable" REQUIRED
		)
	else ()
		find_program(DOT_EXECUTABLE NAMES dot DOC "Graphviz dot executable" REQUIRED)
	endif ()
	set(DG_GraphizDotPath "${DOT_EXECUTABLE}")
	# For cygwin only relative path are working.
	if (EXISTS "${_arg_BASEDIR}/${_arg_LOGO}")
		file(RELATIVE_PATH DG_LogoFile "${_bin_dir}" "${_arg_BASEDIR}/${_arg_LOGO}")
	endif ()
	# Enable when to change the output directory.
	file(RELATIVE_PATH DG_OutputDir "${_bin_dir}" "${_arg_OUTDIR}")
	# Remove possible duplicates.
	list(REMOVE_DUPLICATES _src_list)
	# Replace the list separator ';' with a space and a double quotes in the list to allow names with spaces in it.
	list(JOIN _src_list "\" \"" DG_Source)
	set(DG_Source "\"${DG_Source}\"")
	# Enable when generating Awesome styling output.
	if (DEFINED _arg_THEME AND _arg_THEME)
		#[[
		Required for this theme to work
		GENERATE_TREEVIEW      = YES # optional. Also works without treeview
		DISABLE_INDEX = NO
		FULL_SIDEBAR = NO
		HTML_EXTRA_STYLESHEET  = doxygen-awesome-css/doxygen-awesome.css
		HTML_COLORSTYLE        = LIGHT # required with Doxygen >= 1.9.5
		]]
		Sf_GetGitHubVersionFileUrl(_url "jothepro" "doxygen-awesome-css" "2.4.1")
		FetchContent_Declare(
			doxygen_awesome URL "${_url}"
			#GIT_REPOSITORY "https://github.com/jothepro/doxygen-awesome-css.git" GIT_TAG "v2.4.1" GIT_SHALLOW 1
			TLS_VERIFY ${_TlsCheck} DOWNLOAD_NO_PROGRESS TRUE
		)
		# Download it.
		FetchContent_MakeAvailable(doxygen_awesome)
		# Header
		#file(RELATIVE_PATH DG_HtmlHeader "${_bin_dir}" "${doxygen_awesome_SOURCE_DIR}/doxygen-custom/header.html")
		# CSS files.
		set(DG_HtmlExtraStyleSheet "")
		foreach (_entry "${doxygen_awesome_SOURCE_DIR}/doxygen-awesome.css" "${SfDoxygen_DIR}/tpl/doxygen/amend-any.css")
			file(RELATIVE_PATH _entry "${_bin_dir}" "${_entry}")
			list(APPEND DG_HtmlExtraStyleSheet "${_entry}")
		endforeach ()
		list(JOIN DG_HtmlExtraStyleSheet "\" \"" DG_HtmlExtraStyleSheet)
		set(DG_HtmlExtraStyleSheet "\"${DG_HtmlExtraStyleSheet}\"")
		# Javascript files.
		file(GLOB _JsFiles LIST_DIRECTORIES FALSE RELATIVE "${_bin_dir}" "${doxygen_awesome_SOURCE_DIR}/*.js")
		list(JOIN _JsFiles "\" \"" DG_HtmlExtraFiles)
		unset(_JsFiles)
		set(DG_HtmlExtraFiles "\"${DG_HtmlExtraFiles}\"")
	else ()
		# Fixes source file viewing.
		file(RELATIVE_PATH DG_HtmlExtraStyleSheet "${_bin_dir}" "${SfDoxygen_DIR}/tpl/doxygen/custom.css")
		file(RELATIVE_PATH DG_HtmlExtraFiles "${_bin_dir}" "${_arg_BASEDIR}/favicon.ico")
	endif ()
	# Set the example path for this project it currently only accepts a single directory.
	file(RELATIVE_PATH DG_ExamplePath "${_bin_dir}" "${SF_EXAMPLE_DIR}")
	# Set PlantUML the include path.
	set(DG_PlantUmlIncPath "${_arg_BASEDIR}")
	# Extend the output directory with a 'html' directory.
	set(_HtmlDir "${_arg_OUTDIR}/html")
	# Add a Markdown filter using a python script.
	find_program(PYTHON_EXECUTABLE NAMES "python3" "python" REQUIRED)
	if (WIN32)
		set(DG_FilterPatterns
			"*.md=\"\\\"${PYTHON_EXECUTABLE}\\\" \\\"${CMAKE_CURRENT_FUNCTION_LIST_DIR}/bin/doxygen-md-filter.py\\\"\""
		)
	else ()
		set(DG_FilterPatterns
			"*.md=\"'${PYTHON_EXECUTABLE}' '${CMAKE_CURRENT_FUNCTION_LIST_DIR}/bin/doxygen-md-filter.py'\""
		)
	endif ()
	# Set input and output files for the generation of the actual config file.
	set(_FileIn "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/tpl/doxygen/doxyfile.conf")
	set(_FileOut "${_bin_dir}/doxyfile.conf")
	# Generate the configure the file for doxygen.
	configure_file("${_FileIn}" "${_FileOut}" @ONLY)
	# Create launcher page which can be used from the IDE browser.
	file(COPY "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/tpl/doxygen/open.html" DESTINATION "${_arg_OUTDIR}")
	# Note the option ALL which allows to build the docs together with the application.
	add_custom_target(
		"${_Target}"
		# Remove previous resulting 'html' directory.
		COMMAND ${CMAKE_COMMAND} -E rm -rf "${_HtmlDir}/"
		# Execute Doxygen and generate the document.
		COMMAND ${DOXYGEN_EXECUTABLE} "${_FileOut}"
		WORKING_DIRECTORY "${_bin_dir}"
		COMMENT "Generating documentation with Doxygen"
		VERBATIM USES_TERMINAL
	)
endfunction()
