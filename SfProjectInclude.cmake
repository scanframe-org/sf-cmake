#[[

This include file's purpose is a helper for foreign repositories to modify
it for the ./build.py script to function.

The needs to be included multiple times into CMakeLists.txt file of the toplevel project.

1) Include before project creation.
2) Include direct after project creation before targets are created.
3) Include at the end of the file to modify created targets.

]]

if (NOT DEFINED PROJECT_NAME)

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

else ()

	Sf_GetAllTargets(_targets "${CMAKE_SOURCE_DIR}" TRUE)

	if (NOT _targets)

		# Get the Qt version from the 'build.ini' file.
		ini_read_value(_QtVer "${CMAKE_SOURCE_DIR}/build.ini" "config" "qt-ver" "6.10.1")
		# Install/fetch the Qt Libraries when ENV{QT_VER_DIR} is not set.
		find_package(SfQtLibrary "${_QtVer}" CONFIG REQUIRED)

	else ()

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

		# Add the project in the doc directory when it exists.
		if (EXISTS "${CMAKE_SOURCE_DIR}/doc/CMakeLists.txt")
			add_subdirectory("${CMAKE_SOURCE_DIR}/doc")
		endif ()

		# Add package build config when not building coverage.
		if (NOT CMAKE_BUILD_TYPE STREQUAL "Coverage")
			if (EXISTS "${SF_CPACK_PREPARE_FILE}")
				include("${SF_CPACK_PREPARE_FILE}")
			endif ()
		endif ()

	endif ()
endif ()