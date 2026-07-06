#include "robotics/RobotController.h"

namespace ImFusion::Robotics {

RobotController::RobotController() = default;

void RobotController::reset() {
  ready_ = false;
  speed_ = 0.0;
}

void RobotController::configure(double speed) {
  speed_ = speed;
  ready_ = speed > 0.0;
}

}  // namespace ImFusion::Robotics
