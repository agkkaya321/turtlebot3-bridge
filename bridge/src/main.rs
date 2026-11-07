//! Bridge entry point. HTTP remains available during ROS recovery.
mod config;
mod health;
mod http;
mod ros;
mod sensors;
mod services;
mod state;
mod supervisor;
mod velocity;
mod watch;

use config::Config;
use state::{SharedStatus, SharedTelemetry, Status, Telemetry};
use std::{
    error::Error,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use supervisor::Supervisor;

pub type BridgeResult<T> = Result<T, Box<dyn Error + Send + Sync>>;

fn main() -> BridgeResult<()> {
    let config = Config::from_env()?;
    let running = Arc::new(AtomicBool::new(true));
    let stop_flag = running.clone();
    ctrlc::set_handler(move || stop_flag.store(false, Ordering::SeqCst))?;
    let status: SharedStatus = Arc::new(Mutex::new(Status::waiting("Initializing ROS")));
    let telemetry: SharedTelemetry = Arc::new(Mutex::new(Telemetry::default()));
    // Short queue: the ROS loop drains several entries per cycle.
    let (commands, receiver) = mpsc::sync_channel(8);
    http::start(
        &config.bind,
        commands,
        status.clone(),
        telemetry.clone(),
        (config.max_speed, config.max_angular()),
        running.clone(),
    )?;
    let mut supervisor = Supervisor::new();
    eprintln!(
        "Bridge http://{} -> {}; wheel limit ±{} m/s; GET /ready for status",
        config.bind, config.velocity_topic, config.max_speed
    );

    while running.load(Ordering::SeqCst) {
        match ros::run(
            &config,
            &receiver,
            &status,
            &telemetry,
            &running,
            &mut supervisor,
        ) {
            Ok(()) => break,
            Err(error) => {
                eprintln!("ROS error, retrying in 2 s: {error}");
                let mut failure = Status::waiting(format!("ROS error: {error}"));
                failure.supervisor = supervisor.description.clone();
                state::update(&status, failure);
                // HTTP keeps reporting not ready while the node is rebuilt.
                let retry = Instant::now() + Duration::from_secs(2);
                while running.load(Ordering::SeqCst) && Instant::now() < retry {
                    thread::sleep(config::PERIOD);
                }
            }
        }
    }
    running.store(false, Ordering::SeqCst);
    state::update(&status, Status::waiting("Stopping bridge"));
    supervisor.shutdown();
    Ok(())
}
