cmake_minimum_required(VERSION 3.16)

# This product is built around an ESP32-S3. An explicit IDF_TARGET from the
# environment or an existing build directory still takes precedence.
if(NOT DEFINED IDF_TARGET AND "$ENV{IDF_TARGET}" STREQUAL "")
    set(IDF_TARGET "esp32s3")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(elder_companion_firmware)
