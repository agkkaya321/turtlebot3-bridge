//! TurtleBot3 driver services: sound, motor power, reset.
//! Wait for responses without blocking the 50 ms loop.
use crate::{
    config::{Config, SERVICE_TIMEOUT},
    state::Telemetry,
};
use r2r::{
    std_srvs::srv::{SetBool, Trigger},
    turtlebot3_msgs::srv::Sound,
};
use serde_json::json;
use std::{
    future::Future,
    pin::Pin,
    sync::mpsc::SyncSender,
    task::{Context, Poll},
    time::Instant,
};

type Reply = SyncSender<Result<String, String>>;
type Response = Pin<Box<dyn Future<Output = Result<String, String>>>>;
type Availability = Pin<Box<dyn Future<Output = r2r::Result<()>>>>;

#[derive(Clone, Copy)]
enum Kind {
    Sound,
    MotorPower,
    Reset,
}

const KINDS: [(Kind, &str); 3] = [
    (Kind::Sound, "sound"),
    (Kind::MotorPower, "motor_power"),
    (Kind::Reset, "reset"),
];

struct Watch {
    name: String,
    available: bool,
    probe: Option<Availability>,
}

struct Pending {
    kind: Kind,
    response: Response,
    deadline: Instant,
    reply: Reply,
}

pub struct Services {
    sound: r2r::Client<Sound::Service>,
    motor_power: r2r::Client<SetBool::Service>,
    reset: r2r::Client<Trigger::Service>,
    watches: [Watch; 3],
    pending: Vec<Pending>,
}

fn poll<T>(future: &mut Pin<Box<dyn Future<Output = T>>>) -> Option<T> {
    // Responses arrive through spin_once: no explicit wakeup is needed.
    let mut context = Context::from_waker(futures::task::noop_waker_ref());
    match future.as_mut().poll(&mut context) {
        Poll::Ready(value) => Some(value),
        Poll::Pending => None,
    }
}

fn answer(success: bool, message: String, done: &str) -> Result<String, String> {
    let message = if message.is_empty() {
        done.to_string()
    } else {
        message
    };
    if success {
        Ok(message)
    } else {
        Err(message)
    }
}

impl Services {
    pub fn new(node: &mut r2r::Node, config: &Config) -> r2r::Result<Self> {
        let qos = r2r::QosProfile::services_default;
        let mut services = Self {
            sound: node.create_client(&config.sound_service, qos())?,
            motor_power: node.create_client(&config.motor_power_service, qos())?,
            reset: node.create_client(&config.reset_service, qos())?,
            watches: [
                &config.sound_service,
                &config.motor_power_service,
                &config.reset_service,
            ]
            .map(|name| Watch {
                name: name.clone(),
                available: false,
                probe: None,
            }),
            pending: Vec::new(),
        };
        for (kind, _) in KINDS {
            services.probe(kind)?;
        }
        Ok(services)
    }

    fn probe(&mut self, kind: Kind) -> r2r::Result<()> {
        let future: Availability = match kind {
            Kind::Sound => Box::pin(r2r::Node::is_available(&self.sound)?),
            Kind::MotorPower => Box::pin(r2r::Node::is_available(&self.motor_power)?),
            Kind::Reset => Box::pin(r2r::Node::is_available(&self.reset)?),
        };
        self.watches[kind as usize].probe = Some(future);
        Ok(())
    }

    pub fn sound(&mut self, value: u8, reply: Reply) -> r2r::Result<()> {
        let request = Sound::Request { value };
        let response = self.sound.request(&request)?;
        let response = async move {
            match response.await {
                Ok(r) => answer(r.success, r.message, "Sound played"),
                Err(error) => Err(format!("Service sound : {error}")),
            }
        };
        self.push(Kind::Sound, Box::pin(response), reply);
        Ok(())
    }

    pub fn motor_power(&mut self, enabled: bool, reply: Reply) -> r2r::Result<()> {
        let request = SetBool::Request { data: enabled };
        let response = self.motor_power.request(&request)?;
        let done = if enabled {
            "Motors enabled"
        } else {
            "Motors disabled"
        };
        let response = async move {
            match response.await {
                Ok(r) => answer(r.success, r.message, done),
                Err(error) => Err(format!("Service motor_power : {error}")),
            }
        };
        self.push(Kind::MotorPower, Box::pin(response), reply);
        Ok(())
    }

    pub fn reset(&mut self, reply: Reply) -> r2r::Result<()> {
        let response = self.reset.request(&Trigger::Request::default())?;
        let response = async move {
            match response.await {
                Ok(r) => answer(r.success, r.message, "Reset completed"),
                Err(error) => Err(format!("Service reset : {error}")),
            }
        };
        self.push(Kind::Reset, Box::pin(response), reply);
        Ok(())
    }

    fn push(&mut self, kind: Kind, response: Response, reply: Reply) {
        self.pending.push(Pending {
            kind,
            response,
            deadline: Instant::now() + SERVICE_TIMEOUT,
            reply,
        });
    }

    /// Call after spin_once: deliver responses and expire pending requests.
    pub fn tick(&mut self) -> r2r::Result<()> {
        for watch in &mut self.watches {
            if let Some(probe) = &mut watch.probe {
                if let Some(result) = poll(probe) {
                    watch.available = result.is_ok();
                    watch.probe = None;
                }
            }
        }
        let mut expired = Vec::new();
        let mut index = 0;
        while index < self.pending.len() {
            let pending = &mut self.pending[index];
            let result = poll(&mut pending.response).or_else(|| {
                (Instant::now() >= pending.deadline).then(|| {
                    Err(format!(
                        "No response from service {}: driver missing or service unavailable",
                        self.watches[pending.kind as usize].name
                    ))
                })
            });
            match result {
                Some(result) => {
                    let pending = self.pending.swap_remove(index);
                    if result.is_err() && Instant::now() >= pending.deadline {
                        expired.push(pending.kind);
                    }
                    let _ = pending.reply.send(result);
                }
                None => index += 1,
            }
        }
        for kind in expired {
            // Recheck server availability after a timeout.
            self.watches[kind as usize].available = false;
            self.probe(kind)?;
        }
        Ok(())
    }

    pub fn publish(&self, telemetry: &mut Telemetry) {
        for (kind, key) in KINDS {
            let watch = &self.watches[kind as usize];
            telemetry.services.insert(
                key,
                json!({"name": watch.name, "available": watch.available}),
            );
        }
    }

    /// Notify waiting HTTP clients when ROS is rebuilt.
    pub fn abort(&mut self) {
        for pending in self.pending.drain(..) {
            let _ = pending.reply.send(Err("ROS loop recovering".into()));
        }
    }
}
