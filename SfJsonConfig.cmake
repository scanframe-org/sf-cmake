# FetchContent added in CMake 3.11, downloads during the configure step
include(FetchContent)
# Set the folder for the IDE.
set(CMAKE_FOLDER "Lib/JSON")
# Import Json library.
#[[
FetchContent_Declare(
	"nlohmann-json-${SfJson_VERSION}"
	GIT_REPOSITORY "https://github.com/nlohmann/json.git"
	GIT_SHALLOW 1
	GIT_TAG "v${SfJson_VERSION}"
	)
]]
FetchContent_Declare(
	"nlohmann-json-${SfJson_VERSION}"
	URL "https://github.com/nlohmann/json/releases/download/v${SfJson_VERSION}/json.tar.xz"
	DOWNLOAD_NO_PROGRESS TRUE
)
# Adds nlohmann_json::nlohmann_json
FetchContent_MakeAvailable("nlohmann-json-${SfJson_VERSION}")
# Unset the folder for the IDE.
unset(CMAKE_FOLDER)

### Lines to add to a project using this library.
#[[

# Make the library available.
find_package(SfJson CONFIG REQUIRED)

# Link the library to the target.
target_link_libraries(MyTargetName PRIVATE nlohmann_json::nlohmann_json)

]]


