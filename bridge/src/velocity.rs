//! Traduction des consignes (robot ou roues) en message ROS.
use crate::config::WHEEL_SEPARATION;
use r2r::geometry_msgs::msg::{Twist, TwistStamped};

/// Consigne du robot entier : m/s vers l'avant et rad/s (positif = gauche).
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Velocity {
    pub linear: f64,
    pub angular: f64,
}

impl Velocity {
    pub const ZERO: Self = Self {
        linear: 0.0,
        angular: 0.0,
    };

    /// Robot différentiel : v = (g + d) / 2, ω = (d - g) / L.
    pub fn from_wheels(left: f64, right: f64) -> Self {
        Self {
            linear: (left + right) / 2.0,
            angular: (right - left) / WHEEL_SEPARATION,
        }
    }

    pub fn wheels(&self) -> (f64, f64) {
        let half = self.angular * WHEEL_SEPARATION / 2.0;
        (self.linear - half, self.linear + half)
    }

    /// Vitesses des roues arrondies au 1/10 de mm/s, pour l'affichage.
    pub fn rounded_wheels(&self) -> (f64, f64) {
        let (left, right) = self.wheels();
        let round = |x: f64| (x * 1e4).round() / 1e4;
        (round(left), round(right))
    }

    pub fn is_zero(&self) -> bool {
        self.linear == 0.0 && self.angular == 0.0
    }

    /// Chaque roue reste dans ±max_speed ; la marge absorbe l'arrondi de from_wheels.
    pub fn validate(&self, max_speed: f64) -> Result<(), String> {
        if !self.linear.is_finite() || !self.angular.is_finite() {
            return Err("Vitesses finies requises".into());
        }
        let (left, right) = self.wheels();
        if left.abs() > max_speed + 1e-9 || right.abs() > max_speed + 1e-9 {
            return Err(format!(
                "Vitesse de roue limitée à ±{max_speed:.2} m/s (gauche {left:.3}, droite {right:.3})"
            ));
        }
        Ok(())
    }
}

// Un seul type ROS est publié sur le topic choisi.
pub enum VelocityPublisher {
    Stamped(r2r::Publisher<TwistStamped>),
    Plain(r2r::Publisher<Twist>),
}

impl VelocityPublisher {
    pub fn subscriber_count(&self) -> r2r::Result<usize> {
        match self {
            Self::Stamped(p) => p.get_inter_process_subscription_count(),
            Self::Plain(p) => p.get_inter_process_subscription_count(),
        }
    }

    pub fn publish(&self, velocity: Velocity, clock: &mut r2r::Clock) -> r2r::Result<()> {
        let mut twist = Twist::default();
        twist.linear.x = velocity.linear;
        // Les autres axes restent à zéro : robot différentiel sur le sol.
        twist.angular.z = velocity.angular;
        match self {
            Self::Plain(p) => p.publish(&twist),
            Self::Stamped(p) => {
                let mut message = TwistStamped::default();
                message.header.stamp = r2r::Clock::to_builtin_time(&clock.get_now()?);
                message.header.frame_id = "base_link".into();
                message.twist = twist;
                p.publish(&message)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wheels_round_trip() {
        let velocity = Velocity::from_wheels(-0.03, 0.05);
        let (left, right) = velocity.wheels();
        assert!((left + 0.03).abs() < 1e-12 && (right - 0.05).abs() < 1e-12);
        assert!(
            velocity.angular > 0.0,
            "roue droite plus rapide = tourner à gauche"
        );
    }

    #[test]
    fn each_wheel_is_limited() {
        assert!(Velocity::from_wheels(0.10, 0.10).validate(0.10).is_ok());
        assert!(Velocity::from_wheels(-0.10, 0.10).validate(0.10).is_ok());
        assert!(Velocity {
            linear: 0.08,
            angular: 0.5
        }
        .validate(0.10)
        .is_err());
        assert!(Velocity {
            linear: 0.0,
            angular: f64::NAN
        }
        .validate(0.10)
        .is_err());
    }
}
