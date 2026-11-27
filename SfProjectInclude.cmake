#[[

This include file's purpose is a helper for foreign repositories to modify
it for the ./build.py script to function.

It is added by the 'sf-cmake.py' script, which installs this library into 'cmake/lib' without needing a Git submodule.
Projects not depending on this library therefore do not have to add it as a submodule.

The file needs to be included multiple times in the CMakeLists.txt file of the toplevel project, only when it is found:

  if (EXISTS "${CMAKE_SOURCE_DIR}/cmake/lib/SfProjectInclude.cmake")
    include("${CMAKE_SOURCE_DIR}/cmake/lib/SfProjectInclude.cmake")
  endif ()

1) Include before project creation.
2) Include direct after project creation before targets are created.
3) Include at the end of the file to modify created targets.

]]

if (NOT DEFINED SfBase_FOUND)

	message(STATUS "Inject Before Project: ${CMAKE_CURRENT_LIST_FILE}")
	# Set 'SfBase_FOUND' to make the include file do the final part.
	cmake_language(
		DEFER DIRECTORY "${CMAKE_SOURCE_DIR}"
		CALL set SfBase_FOUND 3
	)
	# Make the project at the end include this script again.
	cmake_language(
		DEFER DIRECTORY "${CMAKE_SOURCE_DIR}"
		#CALL include "${CMAKE_SOURCE_DIR}/cmake/SfFinal.cmake"
		CALL include "${SfBase_DIR}/SfProjectInclude.cmake"
	)

	##!
	# _sf_find_logo(<out_var> <dir1> [<dir2> ...])
	# Sets <out_var> to the first matching logo file, or an empty string if none is found.
	#
	function(_sf_find_logo out_var)
		set(exclude_regex "/(tmp|temp|build|\\.cache)/")
		set(result "")
		foreach(dir IN LISTS ARGN)
			string(PREPEND dir "${CMAKE_SOURCE_DIR}/")
			if(IS_DIRECTORY "${dir}")
				file(GLOB_RECURSE candidates LIST_DIRECTORIES false "${dir}/*logo*")
				list(FILTER candidates EXCLUDE REGEX "${exclude_regex}")
				list(FILTER candidates INCLUDE REGEX "\\.(svg|png|jpg)$")
				if(candidates)
					list(GET candidates 0 result)
					break()
				endif()
			endif()
		endforeach()
		file(RELATIVE_PATH result "${CMAKE_SOURCE_DIR}" "${result}")
		set(${out_var} "${result}" PARENT_SCOPE)
	endfunction()

	list(APPEND CMAKE_PREFIX_PATH "${CMAKE_CURRENT_LIST_DIR}")
	# Package needed for Sf_GetGitTagVersion().
	find_package(SfBase CONFIG REQUIRED)
	# Package setting the correct tool chain according the host and SF_COMPILER.
	find_package(SfToolChain CONFIG REQUIRED)
	# Get the Git versions from the source directory repository of any tag, annotated or not.
	Sf_GetGitTagVersion(_Versions "${CMAKE_SOURCE_DIR}" TRUE)
	# Report the found Git tag found version.
	Sf_ReportGitTagVersion("${_Versions}")
	# Split the list into separate values.
	list(GET _Versions 0 SF_GIT_TAG_VERSION)
	list(GET _Versions 1 SF_GIT_TAG_RC)
	list(GET _Versions 2 SF_GIT_TAG_COMMITS)
	unset(_Versions)

elseif (SfBase_FOUND STREQUAL "1")

	message(STATUS "Inject After Project: ${CMAKE_CURRENT_LIST_FILE}")
	# Up the sentry value.
	set(SfBase_FOUND 2)

	# Get the Qt version from the 'build.ini' file.
	ini_read_value(_QtVer "${CMAKE_SOURCE_DIR}/build.ini" "config" "qt-ver" "6.10.1")
	# Install/fetch the Qt Libraries when ENV{QT_VER_DIR} is not set.
	find_package(SfQtLibrary "${_QtVer}" CONFIG REQUIRED)
	# Only override the project version from the Git tag when the project when one is set and the git version is greater.
	if (NOT CMAKE_PROJECT_VERSION STREQUAL "" AND CMAKE_PROJECT_VERSION VERSION_LESS "${SF_GIT_TAG_VERSION}")
		Sf_SetProjectVersions("${SF_GIT_TAG_VERSION}" CURRENT TOP_LEVEL)
	endif ()

elseif (SfBase_FOUND STREQUAL "3")

	message(STATUS "Inject Final: ${CMAKE_CURRENT_LIST_FILE}")
	# Set sentry.
	set(SfBase_FOUND 3)
	# Get all declared targets.
	Sf_GetAllTargets(_targets "${CMAKE_SOURCE_DIR}" TRUE)
	# Apply the run path to the targets.
	Sf_SetRunPath(TARGETS ${_targets})

	foreach (_target IN LISTS _targets)
		get_target_property(_source_dir "${_target}" SOURCE_DIR)
		set_target_properties(
			${_target}
			PROPERTIES
			# Use the global set value.
			ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_ARCHIVE_OUTPUT_DIRECTORY}"
			LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
			RUNTIME_OUTPUT_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
		)
		# Get the type of the target and add the 'doc' flag when it is a library.
		get_target_property(_type "${_target}" TYPE)
		if (_type MATCHES "^(STATIC|SHARED|MODULE)_LIBRARY$")
			# The 'doc' flag is picked up by the document project.
			Sf_ModifyTargetFlags("${_target}" ADD "doc")
		endif ()

		if (_type MATCHES "^(EXECUTABLE|SHARED_LIBRARY)$")
			# Get the linked libraries.
			get_target_property(_libs ${_target} LINK_LIBRARIES)
			set(_flags)
			if ("Qt${QT_VERSION_MAJOR}::Core" IN_LIST _libs)
				list(APPEND _flags "qt")
			endif ()
			# When the target is an executable.
			if (_type STREQUAL "EXECUTABLE")
				# And when Qt?::Gui is linked.
				if ("Qt${QT_VERSION_MAJOR}::Gui" IN_LIST _libs)
					# Set the target flag 'gui'.
					list(APPEND _flags "gui")
					# And when not.
				else ()
					# Set the target flag 'cli'.
					list(APPEND _flags "cli")
				endif ()
			endif ()
			Sf_ModifyTargetFlags("${_target}" ADD ${_flags})
		endif ()

	endforeach ()

	# Add doxygen project when SfDoxygen was found.
	find_package(SfDoxygen 1.16.1 CONFIG QUIET)
	if (SfDoxygen_FOUND)
		# Include Markdown files recursively except for the root of the project.
		set(_md_includes "*.md" "doc/*.md" "docs/*.md" "src/*.md")
		# Try finding a logo of some kind.
		_sf_find_logo(_logo_image "doc" "docs" "man")
		# Add the 'document' target using auto selected main page.
		Sf_AddDoxygenDocument("document" THEME INCLUDE ${_md_includes} LOGO "${_logo_image}" MAIN "*")
	endif ()

	# Add package build config when not building coverage.
	if (NOT CMAKE_BUILD_TYPE STREQUAL "Coverage")
		if (EXISTS "${SF_CPACK_PREPARE_FILE}")
			include("${SF_CPACK_PREPARE_FILE}")
		endif ()
	endif ()

endif ()
