cmake_minimum_required(VERSION 3.16)
project(WOWKISPICE_GUI LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Find Qt5
find_package(Qt5 COMPONENTS Core Widgets Gui PrintSupport Charts REQUIRED)

include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/src)

# Source files
set(GUI_SRCS
    src/main.cpp
    src/mainwindow.cpp
    include/mainwindow.h
    src/views/schematic_editor.cpp
    include/views/schematic_editor.h
    src/views/waveform_viewer.cpp
    include/views/waveform_viewer.h
    src/views/cosim_dashboard.cpp
    include/views/cosim_dashboard.h
    src/views/code_workspace.cpp
    include/views/code_workspace.h
)

add_executable(wowkispice_gui ${GUI_SRCS})

target_link_libraries(wowkispice_gui PRIVATE
    Qt5::Core
    Qt5::Widgets
    Qt5::Gui
    Qt5::PrintSupport
    Qt5::Charts
)

if(MSVC)
    target_compile_options(wowkispice_gui PRIVATE /W4 /WX /permissive-)
elseif(CMAKE_COMPILER_IS_GNUCXX)
    target_compile_options(wowkispice_gui PRIVATE -Wall -Wextra -Werror -pedantic)
endif()
