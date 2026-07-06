#pragma once

namespace ImFusion::Robotics {

/// Robot motion controller — extended API with lifecycle helpers.
class RobotController {
public:
  RobotController();

  void reset();
  void configure(double speed);
  bool isReady() const { return ready_; }

private:
  bool ready_{false};
  double speed_{0.0};
};

}  // namespace ImFusion::Robotics
