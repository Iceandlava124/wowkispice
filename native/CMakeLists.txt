cmake_minimum_required(VERSION 3.16)
project(wowkispice_native LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Parity with CPython's IEEE-754 doubles.  Without this the compiler is free to
# contract a*b+c into an FMA, which rounds once instead of twice and quietly
# diverges from Python on the ADC-count boundary.
add_compile_options(-ffp-contract=off -Wall -Wextra)

enable_testing()

add_library(wowkispice_core STATIC src/control_law.c)
target_include_directories(wowkispice_core PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include)

find_library(M_LIB m)
if(M_LIB)
  target_link_libraries(wowkispice_core PUBLIC ${M_LIB})
endif()

add_executable(test_control_law tests/test_control_law.c)
target_link_libraries(test_control_law PRIVATE wowkispice_core)
target_include_directories(test_control_law PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/tests)
target_compile_definitions(test_control_law PRIVATE
  "WOSP_FIRMWARE_MAIN_C=\"${CMAKE_CURRENT_SOURCE_DIR}/../firmware/esp32_buck_controller/src/main.c\""
  "WOSP_TEST_TMPDIR=\"${CMAKE_CURRENT_BINARY_DIR}\"")

add_test(NAME control_law COMMAND test_control_law)

# ----------------------------------------------------------------------
# Cross-implementation parity
#
# native/tests/test_control_law.c proves the C port satisfies the assertions
# ported from the Python suite.  These two executables prove something a
# ported test cannot: that both implementations return the SAME numbers for a
# battery neither test was transcribed from.  A transcription error travels
# with its test; a diff does not.
# ----------------------------------------------------------------------
add_executable(parity_control_law tools/parity_control_law.c)
target_link_libraries(parity_control_law PRIVATE wowkispice_core)
target_compile_definitions(parity_control_law PRIVATE
  "WOSP_FIRMWARE_MAIN_C=\"${CMAKE_CURRENT_SOURCE_DIR}/../firmware/esp32_buck_controller/src/main.c\"")

find_package(Python3 COMPONENTS Interpreter)
# Prefer the repository's own virtualenv: it is the interpreter the Python
# gate runs under (tools/run_tests.py), so the parity test should compare
# against the same Python the suite is gated on rather than whatever
# interpreter CMake happens to find first.
if(NOT EXISTS "${Python3_EXECUTABLE}"
   OR NOT "${Python3_EXECUTABLE}" MATCHES "\\.venv")
  if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../.venv/Scripts/python.exe")
    set(Python3_EXECUTABLE
        "${CMAKE_CURRENT_SOURCE_DIR}/../.venv/Scripts/python.exe")
    set(Python3_Interpreter_FOUND TRUE)
  endif()
endif()

if(Python3_Interpreter_FOUND)
  add_test(NAME parity_control_law
           COMMAND ${Python3_EXECUTABLE}
                   ${CMAKE_CURRENT_SOURCE_DIR}/tools/parity_control_law.py
                   $<TARGET_FILE:parity_control_law>)
  # The Python side imports bridge/ from the repository root.
  set_tests_properties(parity_control_law PROPERTIES
                       WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/..)
else()
  message(STATUS "Python3 not found - parity_control_law test not registered "
                 "(the C binary still builds)")
endif()
