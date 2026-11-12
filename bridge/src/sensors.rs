//! Convert sensor messages to JSON for the UI.
//! Non-finite values (out-of-range LiDAR, etc.) become null.
use r2r::{
    geometry_msgs::msg::{Quaternion, Vector3},
    nav_msgs::msg::Odometry,
    sensor_msgs::msg::{BatteryState, Imu, JointState, LaserScan, MagneticField},
    turtlebot3_msgs::msg::SensorState,
};
use serde_json::{json, Value};

/// Round to `digits` decimal places; return null if the value is not finite.
fn num(value: f64, digits: i32) -> Value {
    if !value.is_finite() {
        return Value::Null;
    }
    let scale = 10f64.powi(digits);
    json!((value * scale).round() / scale)
}

fn vector(v: &Vector3, digits: i32) -> Value {
    json!({"x": num(v.x, digits), "y": num(v.y, digits), "z": num(v.z, digits)})
}

fn yaw(q: &Quaternion) -> f64 {
    (2.0 * (q.w * q.z + q.x * q.y)).atan2(1.0 - 2.0 * (q.y * q.y + q.z * q.z))
}

pub fn odometry(message: &Odometry) -> Value {
    let pose = &message.pose.pose;
    let twist = &message.twist.twist;
    json!({
        "x": num(pose.position.x, 4),
        "y": num(pose.position.y, 4),
        "yaw_rad": num(yaw(&pose.orientation), 4),
        "linear_mps": num(twist.linear.x, 4),
        "angular_rad_s": num(twist.angular.z, 4),
    })
}

pub fn sensor_state(message: &SensorState) -> Value {
    json!({
        "bumper": message.bumper,
        "cliff": num(message.cliff.into(), 3),
        "sonar": num(message.sonar.into(), 3),
        "illumination": num(message.illumination.into(), 3),
        "led": message.led,
        "button": message.button,
        "torque": message.torque,
        "left_encoder": message.left_encoder,
        "right_encoder": message.right_encoder,
        "battery_v": num(message.battery.into(), 2),
    })
}

pub fn battery(message: &BatteryState) -> Value {
    // ROS: percentage is between 0 and 1, NaN if unknown.
    json!({
        "voltage_v": num(message.voltage.into(), 2),
        "percentage": num(message.percentage.into(), 3),
        "current_a": num(message.current.into(), 3),
        "present": message.present,
    })
}

pub fn imu(message: &Imu) -> Value {
    json!({
        "yaw_rad": num(yaw(&message.orientation), 4),
        "angular_velocity": vector(&message.angular_velocity, 4),
        "linear_acceleration": vector(&message.linear_acceleration, 3),
    })
}

pub fn magnetic_field(message: &MagneticField) -> Value {
    json!({ "tesla": vector(&message.magnetic_field, 9) })
}

pub fn joint_states(message: &JointState) -> Value {
    let values = |list: &[f64], digits| list.iter().map(|x| num(*x, digits)).collect::<Vec<_>>();
    json!({
        "name": message.name,
        "position_rad": values(&message.position, 4),
        "velocity_rad_s": values(&message.velocity, 4),
    })
}

pub fn scan(message: &LaserScan) -> Value {
    let (low, high) = (message.range_min, message.range_max);
    // A distance outside the sensor limits is not a valid measurement.
    let ranges: Vec<Value> = message
        .ranges
        .iter()
        .map(|&r| {
            if r.is_finite() && r >= low && r <= high {
                num(r.into(), 3)
            } else {
                Value::Null
            }
        })
        .collect();
    json!({
        "angle_min": num(message.angle_min.into(), 6),
        "angle_increment": num(message.angle_increment.into(), 6),
        "range_min": num(low.into(), 3),
        "range_max": num(high.into(), 3),
        "ranges": ranges,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_lidar_ranges_become_null() {
        let mut message = LaserScan::default();
        message.range_min = 0.12;
        message.range_max = 3.5;
        message.ranges = vec![f32::INFINITY, f32::NAN, 0.05, 1.2345, 9.0];
        let body = scan(&message);
        let ranges = body["ranges"].as_array().unwrap();
        assert!(ranges[0].is_null() && ranges[1].is_null() && ranges[2].is_null());
        assert_eq!(ranges[3], json!(1.235));
        assert!(ranges[4].is_null());
        // The resulting JSON remains valid (no literal NaN/Infinity values).
        assert!(serde_json::from_str::<Value>(&body.to_string()).is_ok());
    }

    #[test]
    fn yaw_of_a_quarter_turn() {
        let half = std::f64::consts::FRAC_PI_4;
        let q = Quaternion {
            x: 0.0,
            y: 0.0,
            z: half.sin(),
            w: half.cos(),
        };
        assert!((yaw(&q) - std::f64::consts::FRAC_PI_2).abs() < 1e-9);
    }
}
