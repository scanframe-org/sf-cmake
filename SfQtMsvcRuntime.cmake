# ---------------------------------------------------------------------------
# QtMsvcRuntime.cmake
#
# Selects the MSVC C runtime library (CRT) that matches the CRT used by the
# linked Qt framework.
#
# Mixing CRTs, e.g. building ADS with the debug CRT (/MDd, ucrtbased.dll)
# while Qt was built with the release CRT (/MD, ucrtbase.dll), results in
# heap corruption. Memory allocated in a Qt DLL by one CRT heap gets freed by
# inline Qt header code compiled into ADS using the other CRT heap. This is
# the case for instance with the reference count block of QPointer.
#
# When only release Qt libraries are available (custom Qt builds), a Debug
# build of ADS therefore must use the release CRT as well.
#
# Usage:
#
#   include(QtMsvcRuntime)
#   sf_set_msvc_runtime_from_qt(Qt6::Core)
#
# The call must be made before any targets are created because the
# CMAKE_MSVC_RUNTIME_LIBRARY variable initializes the MSVC_RUNTIME_LIBRARY
# property of targets at creation time. Policy CMP0091 must be set to NEW.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _sf_imported_location(<target> <config> <output>)
#
# Collects the file paths of the binaries of an imported target that are used
# for the given build configuration. The result is a list stored in <output>.
#
# The lookup order mirrors the way CMake itself resolves imported locations:
#   1. MAP_IMPORTED_CONFIG_<CONFIG> mapped configurations.
#   2. IMPORTED_LOCATION_<CONFIG> for the configuration itself.
#   3. The configuration-less IMPORTED_LOCATION property.
#   4. Any configuration listed in IMPORTED_CONFIGURATIONS as last resort,
#      e.g. a Debug build where Qt only provides Release binaries.
# ---------------------------------------------------------------------------
function(_sf_imported_location target config output)
	# Imported location properties use the upper case configuration name.
	string(TOUPPER "${config}" _config)
	# Get the configurations mapped onto the requested one, if any.
	get_target_property(_mapped_configs "${target}" "MAP_IMPORTED_CONFIG_${_config}")
	set(_locations)

	# 1. Use the locations of the mapped configurations.
	if (_mapped_configs AND NOT _mapped_configs MATCHES "-NOTFOUND$")
		foreach (_mapped_config IN LISTS _mapped_configs)
			string(TOUPPER "${_mapped_config}" _mapped_config_upper)
			get_target_property(_location "${target}" "IMPORTED_LOCATION_${_mapped_config_upper}")
			# Only keep locations that are actually set.
			if (_location AND NOT _location MATCHES "-NOTFOUND$")
				list(APPEND _locations "${_location}")
			endif ()
		endforeach ()
	endif ()

	# 2. Use the location of the requested configuration itself.
	if (NOT _locations)
		get_target_property(_location "${target}" "IMPORTED_LOCATION_${_config}")
		if (_location AND NOT _location MATCHES "-NOTFOUND$")
			list(APPEND _locations "${_location}")
		endif ()
	endif ()

	# 3. Use the configuration independent location.
	if (NOT _locations)
		get_target_property(_location "${target}" IMPORTED_LOCATION)
		if (_location AND NOT _location MATCHES "-NOTFOUND$")
			list(APPEND _locations "${_location}")
		endif ()
	endif ()

	# 4. Fall back to all configurations the imported target provides.
	if (NOT _locations)
		get_target_property(_available_configs "${target}" IMPORTED_CONFIGURATIONS)
		foreach (_available_config IN LISTS _available_configs)
			string(TOUPPER "${_available_config}" _available_config_upper)
			get_target_property(_location "${target}" "IMPORTED_LOCATION_${_available_config_upper}")
			if (_location AND NOT _location MATCHES "-NOTFOUND$")
				list(APPEND _locations "${_location}")
			endif ()
		endforeach ()
	endif ()

	# Return each binary only once.
	list(REMOVE_DUPLICATES _locations)
	set(${output} "${_locations}" PARENT_SCOPE)
endfunction()

# ---------------------------------------------------------------------------
# _sf_detect_qt_binary_runtime(<binary> <is_shared> <output>)
#
# Inspects a Qt binary file and determines which MSVC runtime it was built
# with. The result stored in <output> is one of the CMAKE_MSVC_RUNTIME_LIBRARY
# values MultiThreadedDLL, MultiThreadedDebugDLL, MultiThreaded or
# MultiThreadedDebug, or empty when it cannot be determined.
# ---------------------------------------------------------------------------
function(_sf_detect_qt_binary_runtime binary is_shared output)
	# Nothing can be detected without the binary file.
	if (NOT EXISTS "${binary}")
		set(${output} "" PARENT_SCOPE)
		return()
	endif ()

	if (is_shared)
		# A DLL stores the names of the DLLs it imports as plain strings.
		# The debug CRT DLLs carry a 'D' suffix, e.g. VCRUNTIME140D.DLL and
		# UCRTBASED.DLL, so search the binary for any of these names.
		file(STRINGS "${binary}" _debug_crt REGEX "VCRUNTIME[0-9]+D(_[0-9]+)?\\.DLL|UCRTBASED\\.DLL|MSVCP[0-9]+D\\.DLL|MSVCR[0-9]+D\\.DLL")
		# A shared Qt always uses a DLL runtime, only debug or release differs.
		if (_debug_crt)
			set(_runtime MultiThreadedDebugDLL)
		else ()
			set(_runtime MultiThreadedDLL)
		endif ()
	else ()
		# A static library contains linker directives (/DEFAULTLIB:<lib>)
		# naming the CRT import library the objects were compiled for:
		#   MSVCRTD = /MDd, MSVCRT = /MD, LIBCMTD = /MTd, LIBCMT = /MT
		file(STRINGS "${binary}" _crt_directives REGEX "DEFAULTLIB:(MSVCRTD|MSVCRT|LIBCMTD|LIBCMT)")
		# Debug CRT directives take precedence over release ones.
		if (_crt_directives MATCHES "DEFAULTLIB:.*(MSVCRTD|LIBCMTD)")
			# Distinguish between the DLL and the static debug CRT.
			if (_crt_directives MATCHES "DEFAULTLIB:.*MSVCRTD")
				set(_runtime MultiThreadedDebugDLL)
			else ()
				set(_runtime MultiThreadedDebug)
			endif ()
		elseif (_crt_directives MATCHES "DEFAULTLIB:.*(MSVCRT|LIBCMT)")
			# Distinguish between the DLL and the static release CRT.
			if (_crt_directives MATCHES "DEFAULTLIB:.*MSVCRT")
				set(_runtime MultiThreadedDLL)
			else ()
				set(_runtime MultiThreaded)
			endif ()
		endif ()
	endif ()

	set(${output} "${_runtime}" PARENT_SCOPE)
endfunction()

# ---------------------------------------------------------------------------
# sf_detect_qt_msvc_runtime(<target> <output>)
#
# Determines the MSVC runtime of the imported Qt target <target>, e.g.
# Qt6::Core, for all relevant build configurations and stores a value usable
# for CMAKE_MSVC_RUNTIME_LIBRARY in <output>.
#
# When Debug and non-Debug Qt binaries use different runtimes, a generator
# expression selecting the runtime per configuration is returned. <output> is
# empty when no runtime could be determined.
# ---------------------------------------------------------------------------
function(sf_detect_qt_msvc_runtime target output)
	if (NOT TARGET "${target}")
		message(FATAL_ERROR "Cannot detect the MSVC runtime: target '${target}' does not exist")
	endif ()
	# The detection method depends on Qt being a shared or a static library.
	get_target_property(_target_type "${target}" TYPE)
	if (_target_type STREQUAL "SHARED_LIBRARY")
		set(_is_shared TRUE)
	else ()
		set(_is_shared FALSE)
	endif ()
	# Determine the configurations to check:
	# all configurations for multi-config generators (Visual Studio, Ninja
	# Multi-Config), the single build type otherwise, and as last resort the
	# configurations provided by Qt or the CMake default configurations.
	if (CMAKE_CONFIGURATION_TYPES)
		set(_configs ${CMAKE_CONFIGURATION_TYPES})
	elseif (CMAKE_BUILD_TYPE)
		set(_configs "${CMAKE_BUILD_TYPE}")
	else ()
		get_target_property(_configs "${target}" IMPORTED_CONFIGURATIONS)
		if (NOT _configs)
			set(_configs Release Debug RelWithDebInfo MinSizeRel)
		endif ()
	endif ()
	# Detected runtime for the Debug configuration and the other configurations.
	set(_debug_runtime "")
	set(_release_runtime "")
	foreach (_config IN LISTS _configs)
		# Get the Qt binaries used when building this configuration.
		_sf_imported_location("${target}" "${_config}" _locations)
		foreach (_location IN LISTS _locations)
			_sf_detect_qt_binary_runtime("${_location}" "${_is_shared}" _runtime)
			# The first binary giving a result decides for this configuration.
			if (_runtime)
				if (_config STREQUAL "Debug")
					set(_debug_runtime "${_runtime}")
				else ()
					set(_release_runtime "${_runtime}")
				endif ()
				break()
			endif ()
		endforeach ()
	endforeach ()
	# Return an empty result when no binary could be inspected.
	if (NOT _debug_runtime AND NOT _release_runtime)
		set(${output} "" PARENT_SCOPE)
		return()
	endif ()
	if (_debug_runtime AND _release_runtime AND NOT _debug_runtime STREQUAL _release_runtime)
		# Qt provides binaries with different runtimes, so select per configuration.
		set(_runtime "$<$<CONFIG:Debug>:${_debug_runtime}>$<$<NOT:$<CONFIG:Debug>>:${_release_runtime}>")
	elseif (_debug_runtime)
		# Only the Debug configuration was detected or both runtimes are equal.
		set(_runtime "${_debug_runtime}")
	else ()
		# Only non-Debug configurations were detected.
		set(_runtime "${_release_runtime}")
	endif ()
	set(${output} "${_runtime}" PARENT_SCOPE)
endfunction()

# ---------------------------------------------------------------------------
# sf_set_msvc_runtime_from_qt(<target>)
#
# Sets CMAKE_MSVC_RUNTIME_LIBRARY in the calling scope to the runtime used by
# the imported Qt target <target>, so all targets created afterwards, also in
# subdirectories, use the same CRT as Qt.
#
# Does nothing for non-MSVC toolchains (e.g. MinGW only has one CRT) or when
# CMAKE_MSVC_RUNTIME_LIBRARY was already set by the user, a preset or a
# parent project.
#
# Use like:
#   include(QtMsvcRuntime)
#   Sf_SetMsvcRuntimeFromQt(Qt${QT_VERSION_MAJOR}::Core)
# ---------------------------------------------------------------------------
function(Sf_SetMsvcRuntimeFromQt _target)
	# Respect an explicit choice and skip toolchains other than MSVC.
	if (NOT MSVC OR DEFINED CMAKE_MSVC_RUNTIME_LIBRARY)
		return()
	endif ()
	sf_detect_qt_msvc_runtime("${_target}" _runtime)
	if (_runtime)
		# Set the variable in the scope of the caller of this function.
		set(CMAKE_MSVC_RUNTIME_LIBRARY "${_runtime}" PARENT_SCOPE)
		message(STATUS "ADS: using MSVC runtime '${_runtime}' to match ${_target}")
	else ()
		# Keep CMake's default runtime selection when detection fails.
		message(WARNING "ADS: could not determine the MSVC runtime used by ${_target}; keeping CMake's default")
	endif ()
endfunction()
