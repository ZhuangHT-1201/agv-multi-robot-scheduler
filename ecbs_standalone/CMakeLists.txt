cmake_minimum_required(VERSION 3.12)
project(ecbs_standalone VERSION 1.0.0 LANGUAGES CXX)

# Set the C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Optimization flags
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG")
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0")

# Source files
set(ECBS_SOURCES
    src/ecbs_core.cpp
)

set(ECBS_HEADERS
    include/ecbs_core.hpp
)

# Create a static library
add_library(ecbs_core_static STATIC ${ECBS_SOURCES})
target_include_directories(ecbs_core_static PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

# Python bindings
option(BUILD_PYTHON_BINDINGS "Build Python bindings" ON)

if(BUILD_PYTHON_BINDINGS)
    # Find Python
    find_package(Python COMPONENTS Interpreter Development REQUIRED)

    # Find pybind11
    # Read the CMake directory from the Python package
    execute_process(
        COMMAND "${Python_EXECUTABLE}" -c "import pybind11; print(pybind11.get_cmake_dir())"
        OUTPUT_VARIABLE pybind11_CMAKE_DIR
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
        RESULT_VARIABLE pybind11_CMAKE_RESULT
    )

    if(pybind11_CMAKE_RESULT EQUAL 0 AND EXISTS "${pybind11_CMAKE_DIR}")
        # Use the path from the Python package
        list(APPEND CMAKE_PREFIX_PATH "${pybind11_CMAKE_DIR}")
        find_package(pybind11 CONFIG REQUIRED)
    else()
        # Fall back to the standard package lookup
        find_package(pybind11 CONFIG QUIET)

        if(NOT pybind11_FOUND)
            # Fall back to FetchContent
            message(STATUS "pybind11 not found in Python environment, fetching from GitHub...")
            include(FetchContent)
            FetchContent_Declare(
                pybind11
                GIT_REPOSITORY https://github.com/pybind/pybind11.git
                GIT_TAG v2.11.1
            )
            FetchContent_MakeAvailable(pybind11)
        endif()
    endif()

    if(NOT pybind11_FOUND AND NOT TARGET pybind11::pybind11)
        message(FATAL_ERROR "pybind11 not found. Please install: pip install pybind11")
    endif()

    # Create the Python extension
    pybind11_add_module(ecbs_standalone
        bindings/python_bindings.cpp
        ${ECBS_SOURCES}
    )

    target_include_directories(ecbs_standalone PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    )

    # Set the output directory
    if(CMAKE_LIBRARY_OUTPUT_DIRECTORY)
        set_target_properties(ecbs_standalone PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
        )
    else()
        # Default to the source directory
        set_target_properties(ecbs_standalone PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        )
    endif()

    message(STATUS "Python bindings will be built")
    message(STATUS "Python executable: ${Python_EXECUTABLE}")
    message(STATUS "Python version: ${Python_VERSION}")
    message(STATUS "pybind11 version: ${pybind11_VERSION}")
endif()

# Optional test executable
option(BUILD_TESTS "Build test executables" OFF)

if(BUILD_TESTS)
    add_executable(test_ecbs_cpp tests/test_ecbs_cpp.cpp)
    target_link_libraries(test_ecbs_cpp PRIVATE ecbs_core_static)
    target_include_directories(test_ecbs_cpp PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    )
endif()

# Install rules
install(TARGETS ecbs_core_static
    ARCHIVE DESTINATION lib
    LIBRARY DESTINATION lib
    RUNTIME DESTINATION bin
)

install(FILES ${ECBS_HEADERS}
    DESTINATION include/ecbs_standalone
)

# Print configuration
message(STATUS "")
message(STATUS "ECBS Standalone Configuration:")
message(STATUS "  Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "  C++ compiler: ${CMAKE_CXX_COMPILER}")
message(STATUS "  C++ standard: ${CMAKE_CXX_STANDARD}")
message(STATUS "  Python bindings: ${BUILD_PYTHON_BINDINGS}")
message(STATUS "  Build tests: ${BUILD_TESTS}")
message(STATUS "")
