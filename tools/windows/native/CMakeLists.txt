cmake_minimum_required(VERSION 3.20)

project(PiTVXZ LANGUAGES C)

if(MSVC)
    # Keep PiTV-XZ self-contained; do not require the Visual C++ redistributable.
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

include(FetchContent)

# We only need the 0BSD liblzma decoder. Do not build the upstream CLI tools.
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(XZ_NLS OFF CACHE BOOL "" FORCE)
set(XZ_TOOL_XZ OFF CACHE BOOL "" FORCE)
set(XZ_TOOL_XZDEC OFF CACHE BOOL "" FORCE)
set(XZ_TOOL_LZMADEC OFF CACHE BOOL "" FORCE)
set(XZ_TOOL_LZMAINFO OFF CACHE BOOL "" FORCE)
set(XZ_TOOL_SCRIPTS OFF CACHE BOOL "" FORCE)
set(XZ_DOC OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    xz
    GIT_REPOSITORY https://github.com/tukaani-project/xz.git
    # Commit behind the verified signed v5.8.3 tag.
    GIT_TAG 4b73f2ec19a99ef465282fbce633e8deb33691b3
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(xz)

add_executable(PiTV-XZ PiTV-XZ.c)
target_include_directories(PiTV-XZ PRIVATE "${xz_SOURCE_DIR}/src/liblzma/api")
target_link_libraries(PiTV-XZ PRIVATE liblzma)
target_compile_definitions(PiTV-XZ PRIVATE LZMA_API_STATIC)

if(MSVC)
    target_compile_options(PiTV-XZ PRIVATE /O2 /W4)
endif()
