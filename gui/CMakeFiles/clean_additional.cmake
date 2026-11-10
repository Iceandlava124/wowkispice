# Additional clean files
cmake_minimum_required(VERSION 3.16)

if("${CONFIG}" STREQUAL "" OR "${CONFIG}" STREQUAL "Release")
  file(REMOVE_RECURSE
  [[CMakeFiles\wowkispice_gui_autogen.dir\AutogenUsed.txt]]
  [[CMakeFiles\wowkispice_gui_autogen.dir\ParseCache.txt]]
  "wowkispice_gui_autogen"
  )
endif()
