//! Local configuration; no system commands are accepted over HTTP.
use crate::BridgeResult;
use std::{env, time::Duration};

pub const PERIOD: Duration = Duration::from_millis(50);
pub const LEASE: Duration = Duration::from_millis(500);
/// Default wheel speed limit in m/s. Configurable up to BURGER_MAX_SPEED.
pub const DEFAULT_MAX_SPEED: f64 = 0.10;
/// Burger manufacturer maximum speed.
pub const BURGER_MAX_SPEED: f64 = 0.22;
/// Burger wheel separation (param/burger.yaml).
pub const WHEEL_SEPARATION: f64 = 0.160;
pub const TELEMETRY_TIMEOUT: Duration = Duration::from_secs(1);
pub const STATUS_TIMEOUT: Duration = Duration::from_millis(500);
/// Maximum ROS service call timeout (sound, motors, reset).
pub const SERVICE_TIMEOUT: Duration = Duration::from_millis(2500);
/// Maximum number of topics watched on demand.
pub const MAX_WATCHES: usize = 8;

pub struct Config {
    pub camera: crate::camera::Config,
    pub bind: String,
    pub namespace: String,
    pub velocity_topic: String,
    pub odometry_topic: String,
    pub sensor_topic: String,
    pub battery_topic: String,
    pub imu_topic: String,
    pub scan_topic: String,
    pub magnetic_topic: String,
    pub joint_topic: String,
    pub sound_service: String,
    pub motor_power_service: String,
    pub reset_service: String,
    pub stamped: bool,
    pub autostart: bool,
    pub max_speed: f64,
}

impl Config {
    pub fn from_env() -> BridgeResult<Self> {
        let namespace = env::var("ROBOT_NAMESPACE").unwrap_or_default();
        let namespace = namespace.trim_matches('/').to_string();
        let name = |variable: &str, name: &str| {
            env::var(variable).unwrap_or_else(|_| {
                if namespace.is_empty() {
                    format!("/{name}")
                } else {
                    format!("/{namespace}/{name}")
                }
            })
        };
        let stamped = match env::var("CMD_VEL_TYPE").as_deref().unwrap_or("stamped") {
            "stamped" => true,
            "twist" => false,
            _ => return Err("CMD_VEL_TYPE must be stamped or twist".into()),
        };
        let autostart = match env::var("ROS_AUTOSTART").as_deref().unwrap_or("true") {
            "true" => true,
            "false" => false,
            _ => return Err("ROS_AUTOSTART must be true or false".into()),
        };
        let max_speed = match env::var("MAX_SPEED_MPS") {
            Err(_) => DEFAULT_MAX_SPEED,
            Ok(text) => match text.trim().parse::<f64>() {
                Ok(value) if value > 0.0 && value <= BURGER_MAX_SPEED => value,
                _ => return Err("MAX_SPEED_MPS must be greater than 0 and at most 0.22".into()),
            },
        };
        Ok(Self {
            camera: crate::camera::Config::from_env(&namespace)?,
            bind: env::var("BRIDGE_BIND").unwrap_or_else(|_| "127.0.0.1:8000".into()),
            velocity_topic: name("CMD_VEL_TOPIC", "cmd_vel"),
            odometry_topic: name("ODOM_TOPIC", "odom"),
            sensor_topic: name("SENSOR_STATE_TOPIC", "sensor_state"),
            battery_topic: name("BATTERY_TOPIC", "battery_state"),
            imu_topic: name("IMU_TOPIC", "imu"),
            scan_topic: name("SCAN_TOPIC", "scan"),
            magnetic_topic: name("MAGNETIC_FIELD_TOPIC", "magnetic_field"),
            joint_topic: name("JOINT_STATES_TOPIC", "joint_states"),
            sound_service: name("SOUND_SERVICE", "sound"),
            motor_power_service: name("MOTOR_POWER_SERVICE", "motor_power"),
            reset_service: name("RESET_SERVICE", "reset"),
            namespace,
            stamped,
            autostart,
            max_speed,
        })
    }

    /// Maximum in-place rotation: both wheels at max_speed in opposite directions.
    pub fn max_angular(&self) -> f64 {
        2.0 * self.max_speed / WHEEL_SEPARATION
    }
}
