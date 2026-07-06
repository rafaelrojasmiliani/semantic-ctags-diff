#pragma once

namespace ImFusion::Robotics {

/// Robot motion controller — initial revision with construction only.
class RobotController {
public:
  RobotController();

private:
  bool ready_{false};
};

}  // namespace ImFusion::Robotics
