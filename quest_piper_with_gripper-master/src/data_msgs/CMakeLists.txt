cmake_minimum_required(VERSION 2.8.3)
project(data_msgs)
add_definitions(-w)
set(USE_NOETIC true)

set(CMAKE_BUILD_TYPE "Release")
if(USE_NOETIC)
  set(CMAKE_CXX_FLAGS "-std=c++14")
else()
  set(CMAKE_CXX_FLAGS "-std=c++11")
endif()
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -Wall -g -pthread")

if(USE_NOETIC)
  ADD_DEFINITIONS(-D_USENOETIC=\"${USE_NOETIC}\")
endif()

find_package(catkin REQUIRED COMPONENTS
  tf
  roscpp
  rospy
  cv_bridge
  # pcl library
  pcl_conversions
  # msgs
  std_msgs
  sensor_msgs
  geometry_msgs
  nav_msgs
  message_generation
  visualization_msgs
  rosbag
  )
find_package(PkgConfig)
find_package(Boost REQUIRED COMPONENTS timer)

set(lib_DIR /usr/lib/x84_64-linux-gnu)

link_directories(${lib_DIR})

add_message_files(
  DIRECTORY msg
  FILES
  Gripper.msg
  CaptureStatus.msg
  TeleopStatus.msg
  LocalizationStatus.msg
  ArmControlStatus.msg
)

add_service_files(
  DIRECTORY srv
  FILES
  CaptureService.srv
)

generate_messages(
  DEPENDENCIES
  geometry_msgs
  std_msgs
  nav_msgs
  sensor_msgs
)

catkin_package(
  # INCLUDE_DIRS include
  DEPENDS PCL EIGEN3 jsoncpp
  CATKIN_DEPENDS
  std_msgs
  nav_msgs
  geometry_msgs
  sensor_msgs
  message_runtime
  message_generation
  visualization_msgs
)

# set(CSF_DIR "/usr/local")
# include directories
include_directories(
	# include
	${catkin_INCLUDE_DIRS}
	${PCL_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
  ${Jsoncpp_INCLUDE_DIRS}
)

# link directories
link_directories(
	include
	${PCL_LIBRARY_DIRS}
  ${OpenCV_LIBRARY_DIRS}
  ${Jsoncpp_INCLUDE_DIRS}
)

###########
## Build ##
###########


#############
## install ##
#############

install(DIRECTORY
  msg
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)
