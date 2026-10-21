//! Readiness matérielle observée, distincte de la santé des processus ROS.
use crate::config::TELEMETRY_TIMEOUT;
use r2r::{nav_msgs::msg::Odometry, turtlebot3_msgs::msg::SensorState};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[derive(Default)]
pub struct Health {
    odom_seen: Option<Instant>,
    sensor_seen: Option<Instant>,
    odom_valid: bool,
    torque: bool,
    battery_valid: bool,
}

fn fresh(time: Option<Instant>) -> bool {
    time.is_some_and(|time| time.elapsed() < TELEMETRY_TIMEOUT)
}

fn sample_time(stamp: &r2r::builtin_interfaces::msg::Time) -> Option<Instant> {
    let Ok(now) = SystemTime::now().duration_since(UNIX_EPOCH) else {
        return None;
    };
    let seconds = f64::from(stamp.sec) + f64::from(stamp.nanosec) / 1e9;
    let age = now.as_secs_f64() - seconds;
    if stamp.nanosec >= 1_000_000_000 || !(-0.1..1.0).contains(&age) {
        return None;
    }
    // Compter aussi le temps passé en transport, pas seulement depuis réception.
    Instant::now().checked_sub(Duration::from_secs_f64(age.max(0.0)))
}

impl Health {
    pub fn odometry(&mut self, message: &Odometry) {
        self.odom_seen = sample_time(&message.header.stamp);
        let p = &message.pose.pose.position;
        let q = &message.pose.pose.orientation;
        let v = &message.twist.twist.linear;
        let w = &message.twist.twist.angular;
        self.odom_valid = [
            p.x, p.y, p.z, q.x, q.y, q.z, q.w, v.x, v.y, v.z, w.x, w.y, w.z,
        ]
        .iter()
        .all(|x| x.is_finite())
            && (q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w) > 0.0;
    }

    pub fn sensors(&mut self, message: &SensorState) {
        self.sensor_seen = sample_time(&message.header.stamp);
        self.torque = message.torque;
        // Vérification de cohérence seulement, pas une estimation d'autonomie.
        self.battery_valid = message.battery.is_finite() && message.battery > 0.0;
    }

    pub fn ros_alive(&self) -> bool {
        fresh(self.odom_seen) && fresh(self.sensor_seen)
    }

    pub fn reason(&self, subscribers: usize) -> Option<&'static str> {
        if !fresh(self.sensor_seen) {
            Some("État du robot absent ou trop ancien")
        } else if !fresh(self.odom_seen) {
            Some("Odométrie absente ou trop ancienne")
        } else if subscribers == 0 {
            Some("Aucun abonné compatible au topic de vitesse")
        } else if !self.odom_valid {
            Some("Odométrie invalide")
        } else if !self.torque {
            Some("Moteurs désactivés : intervention nécessaire")
        } else if !self.battery_valid {
            Some("Mesure de batterie invalide")
        } else {
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn healthy() -> Health {
        Health {
            odom_seen: Some(Instant::now()),
            sensor_seen: Some(Instant::now()),
            odom_valid: true,
            torque: true,
            battery_valid: true,
        }
    }

    #[test]
    fn readiness_needs_hardware_data_and_a_velocity_subscriber() {
        assert!(Health::default().reason(1).is_some());
        assert!(healthy().reason(0).is_some());
        assert!(healthy().reason(1).is_none());
    }

    #[test]
    fn disabled_motors_do_not_mean_ros_has_crashed() {
        let mut health = healthy();
        health.torque = false;
        assert!(health.ros_alive());
        assert!(health.reason(1).is_some());
    }

    #[test]
    fn stale_telemetry_loses_readiness() {
        let mut health = healthy();
        health.sensor_seen = Some(Instant::now() - Duration::from_secs(2));
        assert!(!health.ros_alive());
        assert!(health.reason(1).is_some());
    }
}
