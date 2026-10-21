//! État partagé avec HTTP ; une boucle ROS figée ne peut rester « ready ».
use crate::{config::STATUS_TIMEOUT, velocity::Velocity};
use serde_json::{json, Map, Value};
use std::{
    collections::BTreeMap,
    sync::{mpsc::SyncSender, Arc, Mutex},
    time::Instant,
};

/// Demandes transmises par HTTP à la boucle ROS.
pub enum Request {
    Velocity(Velocity),
    MotorPower(bool),
    Sound(u8),
    Reset,
    Watch(String),
    Unwatch(String),
}

pub struct Command {
    pub request: Request,
    pub received_at: Instant,
    pub reply: SyncSender<Result<String, String>>,
}

pub struct Status {
    pub ready: bool,
    pub reason: String,
    pub ros_alive: bool,
    pub supervisor: String,
    pub updated: Instant,
}

pub type SharedStatus = Arc<Mutex<Status>>;

impl Status {
    pub fn waiting(reason: impl Into<String>) -> Self {
        Self {
            ready: false,
            reason: reason.into(),
            ros_alive: false,
            supervisor: "initialisation".into(),
            updated: Instant::now(),
        }
    }

    pub fn is_ready(&self) -> bool {
        self.ready && self.updated.elapsed() < STATUS_TIMEOUT
    }

    pub fn label(&self) -> &'static str {
        if self.is_ready() {
            "ready"
        } else {
            "not ready"
        }
    }

    pub fn json(&self) -> Value {
        let fresh = self.updated.elapsed() < STATUS_TIMEOUT;
        json!({
            "status": self.label(),
            "reason": if !fresh && self.ready { "Boucle ROS sans réponse" } else { self.reason.as_str() },
            "ros_alive": fresh && self.ros_alive,
            "supervisor": self.supervisor,
        })
    }
}

pub fn update(shared: &SharedStatus, status: Status) {
    *shared.lock().unwrap_or_else(|error| error.into_inner()) = status;
}

/// Dernières valeurs des capteurs, pour affichage seulement :
/// la readiness reste calculée par health.rs dans la boucle ROS.
#[derive(Default)]
pub struct Telemetry {
    sensors: BTreeMap<String, (Instant, Value)>,
    pub watched: BTreeMap<String, (String, Option<(Instant, Value)>)>,
    pub services: BTreeMap<&'static str, Value>,
    pub topics: Vec<(String, Vec<String>)>,
    pub velocity: Velocity,
}

pub type SharedTelemetry = Arc<Mutex<Telemetry>>;

fn age(time: &Instant) -> u64 {
    time.elapsed().as_millis() as u64
}

impl Telemetry {
    pub fn set(&mut self, key: &str, value: Value) {
        self.sensors.insert(key.into(), (Instant::now(), value));
    }

    pub fn json(&self, max_speed: f64, max_angular: f64) -> Value {
        let sensors: Map<String, Value> = self
            .sensors
            .iter()
            .map(|(key, (time, data))| (key.clone(), json!({"age_ms": age(time), "data": data})))
            .collect();
        let watched: Map<String, Value> = self
            .watched
            .iter()
            .map(|(topic, (kind, last))| {
                let last = last.as_ref();
                (
                    topic.clone(),
                    json!({
                        "type": kind,
                        "age_ms": last.map(|(time, _)| age(time)),
                        "data": last.map(|(_, data)| data),
                    }),
                )
            })
            .collect();
        let (left, right) = self.velocity.rounded_wheels();
        json!({
            "sensors": sensors,
            "watched": watched,
            "services": self.services,
            "command": {
                "linear_mps": self.velocity.linear,
                "angular_rad_s": self.velocity.angular,
                "left_mps": left,
                "right_mps": right,
            },
            "limits": {"wheel_mps": max_speed, "angular_rad_s": max_angular},
        })
    }

    pub fn topics_json(&self) -> Value {
        let topics: Vec<Value> = self
            .topics
            .iter()
            .map(|(name, types)| json!({"name": name, "types": types}))
            .collect();
        json!({ "topics": topics })
    }
}

pub fn lock<T>(shared: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    shared.lock().unwrap_or_else(|error| error.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn a_frozen_ros_loop_cannot_stay_ready() {
        let mut state = Status::waiting("ok");
        state.ready = true;
        assert_eq!(state.label(), "ready");
        state.updated = Instant::now() - Duration::from_secs(1);
        assert_eq!(state.label(), "not ready");
        assert_eq!(state.json()["ros_alive"], false);
    }

    #[test]
    fn telemetry_reports_age_and_limits() {
        let mut telemetry = Telemetry::default();
        telemetry.set("battery", json!({"voltage": 12.1}));
        let body = telemetry.json(0.1, 1.25);
        assert_eq!(body["sensors"]["battery"]["data"]["voltage"], 12.1);
        assert!(body["sensors"]["battery"]["age_ms"].as_u64().unwrap() < 1000);
        assert_eq!(body["limits"]["wheel_mps"], 0.1);
    }
}
