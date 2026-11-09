cmake_minimum_required(VERSION 3.19)
project(mterrain_embedding_smoke LANGUAGES CXX)

get_filename_component(MTERRAIN_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
add_subdirectory("${MTERRAIN_ROOT}/gdextension/godot-cpp" godot-cpp)
set(MTERRAIN_PROFILE runtime CACHE STRING "Embedding fixture profile" FORCE)
add_subdirectory("${MTERRAIN_ROOT}/gdextension" terrain)

# The embedding application supplies its own entry point through public headers.
add_library(mterrain_embedding SHARED register_types.cpp)
target_link_libraries(mterrain_embedding PRIVATE mterrain)
get_target_property(suffix godot-cpp GODOTCPP_SUFFIX)
get_target_property(platform godot-cpp GODOTCPP_PLATFORM)
get_target_property(arch godot-cpp GODOTCPP_ARCH)
get_target_property(target godot-cpp GODOTCPP_TARGET)
set(project_dir "${CMAKE_CURRENT_BINARY_DIR}/project")
set_target_properties(mterrain_embedding PROPERTIES
    CXX_STANDARD 17 CXX_VISIBILITY_PRESET hidden
    OUTPUT_NAME "MTerrainEmbedded${suffix}"
    LIBRARY_OUTPUT_DIRECTORY "${project_dir}/mterrain")
file(MAKE_DIRECTORY "${project_dir}/.godot")
configure_file(project.godot "${project_dir}/project.godot" COPYONLY)
configure_file(smoke.gd "${project_dir}/smoke.gd" COPYONLY)
configure_file("${MTERRAIN_ROOT}/tests/full_profile_smoke/extension_list.cfg"
    "${project_dir}/.godot/extension_list.cfg" COPYONLY)
find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)
add_custom_command(TARGET mterrain_embedding POST_BUILD
    COMMAND "${Python3_EXECUTABLE}" "${MTERRAIN_ROOT}/gdextension/mterrain_build_profile.py"
        --target "${target}" --manifest-source "${MTERRAIN_ROOT}/gdextension/MTerrain.txt"
        --manifest-output "${project_dir}/mterrain/MTerrain.gdextension"
        --platform "${platform}" --arch "${arch}" --library "$<TARGET_FILE_NAME:mterrain_embedding>"
    VERBATIM)
