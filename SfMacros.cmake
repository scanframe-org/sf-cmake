##
## This file is included by SfBase.
##

##!
# Used as a sub-macro to macro 'Sf_AddImportLibrary'.
#
macro(Sf_PopulateTargetProperties TargetName _Configuration _LibLocation _ImplibLocation)
	# Seems a relative directory is not working using REALPATH.
	Sf_GetFilenameComponent(_imported_location "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}/${_LibLocation}" REALPATH)
	# When this fails on a library which is part of the project the order of add_subdirectory(...) is incorrect.
	Sf_CheckFileExists(${_imported_location})
	set_target_properties(${TargetName} PROPERTIES "IMPORTED_LOCATION_${_Configuration}" ${_imported_location})
	if (NOT _ImplibLocation STREQUAL "")
		set(_imported_implib "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}/${_ImplibLocation}")
		Sf_CheckFileExists(${_imported_implib})
		set_target_properties(${TargetName} PROPERTIES "IMPORTED_IMPLIB_${_Configuration}" ${_imported_implib})
	endif ()
endmacro()

##!
# Adds a named target as import library to the current project when the current
# top project does not have this target configured and when is does it is ignored.
#
macro(Sf_AddImportLibrary TargetName)
	# When the target exists ignore it.
	if (TARGET ${TargetName})
		message(VERBOSE "Not adding (${PROJECT_NAME}) library ${TargetName} already part of build and ignored.")
	else ()
		message(VERBOSE "Adding (${PROJECT_NAME}) library: ${TargetName}")
		add_library(${TargetName} SHARED IMPORTED)
		if (WIN32)
			Sf_PopulateTargetProperties(${TargetName} DEBUG "lib${TargetName}.dll" "lib${TargetName}.dll.a")
		else ()
			Sf_PopulateTargetProperties(${TargetName} DEBUG "lib${TargetName}.so" "")
		endif ()
	endif ()
endmacro()

##!
# Works around the cmake bug with sources and binary directory on a shared drive.
#
function(Sf_WorkAroundSmbShare)
	#[[
		# Check if the environment var exists telling us that cmake is running on Windows.
		if (EXISTS "$ENV{ComSpec}")
			set(_Command "PowerShell.exe")
			string(REPLACE "/" "\\" _Script "${SfMacros_DIR}/bin/SmbShareWorkAround.ps1")
			execute_process(COMMAND "${_Command}" "${_Script}" "${CMAKE_BINARY_DIR}" OUTPUT_VARIABLE _Result RESULT_VARIABLE _ExitCode)
		endif ()
		#message(STATUS ${_Result})
		# Validate the exit code.
		if (_ExitCode GREATER "0")
			message(SEND_ERROR "Failed execution of script: ${_Script}")
		endif ()
	]]
endfunction()

##!
# Get all source files from the passed targets.
#  @param _Targets  The list containing all found targets
#  @param _OutVar Output variable returning a list variable.
#
function(Sf_GetTargetSource _Targets _OutVar)
	# Create or recreate empty variable since this is global namespace.
	set(_ActiveSources)
	# Iterate through the targets.
	foreach (_target IN LISTS _Targets)
		# Get the source list from the target.
		get_target_property(_Sources ${_target} SOURCES)
		# Append the target source list to the collection.
		list(APPEND _ActiveSources ${_Sources})
	endforeach ()
	# For convenience sort the list.
	list(SORT _ActiveSources)
	# Since some targets have the same sources remove duplicates.
	list(REMOVE_DUPLICATES _ActiveSources)
	# Assign the passed variable.
	set("${_OutVar}" "${_ActiveSources}" PARENT_SCOPE)
endfunction()


##!
# Checks if the passed path is a symlink.
# Sets the '_ResultVar' variable to TRUE or FALSE.
# Returns false when the path does not exist.
#
function(Sf_IsSymlink _Path _ResultVar)
	# Check if the variable exists
	if (NOT EXISTS "${_Path}")
		set(_ResultVar FALSE PARENT_SCOPE)
		return()
	endif ()
	# When the host system is not windows.
	if ("${CMAKE_HOST_SYSTEM_NAME}" STREQUAL "Windows")
		# Windows doesn't have symlinks in the same way, but it has junctions and symlinks and are treated the same way.
		execute_process(
			COMMAND cmd /c "dir /al \"${_Path}\""
			OUTPUT_VARIABLE _output
			ERROR_VARIABLE _error
			RESULT_VARIABLE _res
		)
		if (_res EQUAL 0)
			# Check for <JUNCTION> or <SYMLINK> in the output.
			string(FIND "${_output}" "<JUNCTION>" is_junction)
			string(FIND "${_output}" "<SYMLINK>" is_symlink)
			if (is_junction GREATER -1 OR is_symlink GREATER -1)
				set(${_ResultVar} TRUE PARENT_SCOPE)
			else ()
				set(${_ResultVar} FALSE PARENT_SCOPE)
			endif ()
		else ()
			set(${_ResultVar} FALSE PARENT_SCOPE)
		endif ()
	else ()
		# Unix-like systems
		execute_process(
			COMMAND stat -c "%F" "${_Path}"
			OUTPUT_VARIABLE _file_type
			RESULT_VARIABLE _res
			ERROR_VARIABLE _error
		)
		if (_res EQUAL 0)
			string(STRIP "${_file_type}" _file_type)
			if (_file_type STREQUAL "symbolic link")
				set(${_ResultVar} TRUE PARENT_SCOPE)
			else ()
				set(${_ResultVar} FALSE PARENT_SCOPE)
			endif ()
		else ()
			message(STATUS "Error checking _Path: ${_Path} - ${_error}")
			# When not found the path sure is not a symbolic link.
			set(${_ResultVar} FALSE PARENT_SCOPE)
		endif ()
	endif ()
endfunction()

##!
# Finds all named subdirectories in a tree.
# @param _OutVar Variable receiving the resulting directories.
# @param _RootDir Root of the directory tree.
# @param _RelativeToDir Result is relative to this directory.
# @param _SubDir Names of the subdirectory to find.
#
function(Sf_GetNamedSubdirectories  _OutVar _RootDir _RelativeToDir _SubDir)
	get_filename_component(root_abs "${_RootDir}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
	get_filename_component(rel_abs  "${_RelativeToDir}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
	# Collect every entry below the root, directories included
	file(GLOB_RECURSE all_entries LIST_DIRECTORIES TRUE "${root_abs}/*")
	set(result)
	foreach(entry IN LISTS all_entries)
		if(IS_DIRECTORY "${entry}")
			get_filename_component(name "${entry}" NAME)
			list(FIND _SubDir "${name}" idx)
			if(NOT idx EQUAL -1)
				file(RELATIVE_PATH rel "${rel_abs}" "${entry}")
				list(APPEND result "${rel}")
			endif()
		endif()
	endforeach()
	list(SORT result)
	set(${_OutVar} "${result}" PARENT_SCOPE)
endfunction()

##!
# Gets release versions from a GitHub repository.
# @param _Owner Name of owner of the repository.
# @param _Repository Name of the owners repository.
# @param Optional boolean true for latest version only.
# @param Optional string for the prefix of the version (by default 'v' or 'Release_'.
#
function(Sf_GetGitHubVersions _VarOut _Owner _Repository)
	# Get the first optional argument.
	Sf_GetOptionalArgument(_latest 0 "${ARGN}")
	Sf_GetOptionalArgument(_prefix 1 "${ARGN}")
	set(_Options "--owner" "${_Owner}" "--repo" "${_Repository}")
	# When argument was passed.
	if (DEFINED _prefix)
		# Be aware empty arguments cannot be passed in an options array.
		list(APPEND _Options "--prefix" "'${_prefix}'")
	endif ()
	if (_latest)
		# Set default version to the latest.
		list(APPEND _Options "--latest")
	else ()
		list(APPEND _Options "--joined")
	endif ()
	cmake_path(CONVERT "${CMAKE_CURRENT_BINARY_DIR}/_cache" TO_NATIVE_PATH_LIST _NativeCacheDir)
	#cmake_path(NATIVE_PATH "${CMAKE_CURRENT_BINARY_DIR}" _CacheDir)
	# Make the cache dir to be in the binary directory so when that is deleted the cache is too.
	list(APPEND _Options "--cache-dir" "${_NativeCacheDir}")
	find_program(PYTHON_EXECUTABLE NAMES "python3" "python" REQUIRED)
	if (PYTHON_EXECUTABLE)
		execute_process(
			COMMAND ${PYTHON_EXECUTABLE} "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/bin/github-versions.py" ${_Options}
			WORKING_DIRECTORY "${CMAKE_CURRENT_FUNCTION_LIST_DIR}"
			OUTPUT_VARIABLE _Versions
			OUTPUT_STRIP_TRAILING_WHITESPACE
			ERROR_STRIP_TRAILING_WHITESPACE
			COMMAND_ERROR_IS_FATAL ANY
			ECHO_OUTPUT_VARIABLE
			ECHO_ERROR_VARIABLE
		)
	endif ()
	if (_Versions STREQUAL "")
		set(${_VarOut} "${_VarOut}-NOTFOUND" PARENT_SCOPE)
		return()
	else ()
		set(${_VarOut} "${_Versions}" PARENT_SCOPE)
	endif ()
endfunction()

##!
# Gets the versioned URL from the given GitHub repository.
# @param _Owner Name of owner of the repository.
# @param _Repository Name of the owners repository.
# @param _TagHash tag or hash of the version.
#
function(Sf_GetGitHubVersionFileUrl _VarOut _Owner _Repository _TagHash)
	set(${_VarOut} "https://github.com/${_Owner}/${_Repository}/archive/refs/tags/v${_TagHash}.tar.gz" PARENT_SCOPE)
endfunction()

##!
# Gets latest release version from a GitHub repository.
# @param _Owner Name of owner of the repository.
# @param _Repository Name of the owners repository.
#
function(Sf_GetGitHubVersion _VarOut _Owner _Repository)
	Sf_GetGitHubVersions(_Version "${_Owner}" "${_Repository}" TRUE)
	if (_Version STREQUAL "")
		set(${_VarOut} "${_VarOut}-NOTFOUND" PARENT_SCOPE)
		return()
	else ()
		set(${_VarOut} "${_Version}" PARENT_SCOPE)
	endif ()
endfunction()
