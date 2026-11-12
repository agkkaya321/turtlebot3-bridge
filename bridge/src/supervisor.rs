//! Supervise only the process group started by this bridge (Linux).
use crate::config::Config;
use nix::{
    errno::Errno,
    sys::signal::{killpg, Signal},
    unistd::Pid,
};
use std::{
    os::unix::process::CommandExt,
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

const DISCOVERY: Duration = Duration::from_secs(5);
const STARTUP: Duration = Duration::from_secs(30);
const STALLED: Duration = Duration::from_secs(5);
const STOP_GRACE: Duration = Duration::from_secs(3);

struct ManagedProcess {
    child: Child,
    group: Pid,
    started: Instant,
    last_alive: Instant,
    healthy_since: Option<Instant>,
    stopping: Option<Instant>,
}

pub struct Supervisor {
    process: Option<ManagedProcess>,
    next_start: Instant,
    retry_seconds: u64,
    pub description: String,
}

fn signal_group(group: Pid, signal: Signal) -> Result<(), Errno> {
    match killpg(group, signal) {
        Ok(()) | Err(Errno::ESRCH) => Ok(()),
        Err(error) => Err(error),
    }
}

impl Supervisor {
    pub fn new() -> Self {
        Self {
            process: None,
            next_start: Instant::now() + DISCOVERY,
            retry_seconds: 2,
            description: "Discovering existing drivers".into(),
        }
    }

    pub fn allows_motion(&self) -> bool {
        self.process.as_ref().is_none_or(|p| p.stopping.is_none())
    }

    /// Called each cycle. No blocking wait()/sleep() while driving.
    /// stop_motion sends zero velocity BEFORE terminating a process group.
    pub fn tick(
        &mut self,
        config: &Config,
        ros_alive: bool,
        external: bool,
        mut stop_motion: impl FnMut(),
    ) {
        let now = Instant::now();
        if let Some(process) = &mut self.process {
            let exit = process.child.try_wait();
            if process.stopping.is_none() {
                let failure = match exit {
                    Ok(Some(status)) => Some(format!("Bringup exited: {status}")),
                    Err(error) => Some(format!("Process unavailable: {error}")),
                    Ok(None) => {
                        if ros_alive {
                            process.last_alive = now;
                            let since = process.healthy_since.get_or_insert(now);
                            if since.elapsed() >= Duration::from_secs(60) {
                                self.retry_seconds = 2;
                            }
                        } else {
                            process.healthy_since = None;
                        }
                        if process.started.elapsed() >= STARTUP
                            && process.last_alive.elapsed() >= STALLED
                        {
                            Some("Persistent loss of ROS data".into())
                        } else {
                            None
                        }
                    }
                };
                if let Some(reason) = failure {
                    stop_motion();
                    process.stopping = Some(now);
                    self.description = format!("{reason}; stopping before restart");
                    if let Err(error) = signal_group(process.group, Signal::SIGINT) {
                        eprintln!("Unable to stop bringup: {error}");
                    }
                } else {
                    self.description = if ros_alive {
                        "Supervised bringup active"
                    } else {
                        "Starting bringup / waiting for data"
                    }
                    .into();
                }
            }
            if process
                .stopping
                .is_some_and(|time| time.elapsed() >= STOP_GRACE)
            {
                // Also terminate remaining children if ros2 launch has already exited.
                if let Err(error) = signal_group(process.group, Signal::SIGKILL) {
                    self.description = format!("Cleanup failed: {error}; restart blocked");
                    return;
                }
                if matches!(process.child.try_wait(), Ok(Some(_))) {
                    self.process = None;
                    self.schedule_retry();
                }
            }
            return;
        }

        if !config.autostart {
            self.description = "Automatic startup disabled".into();
            return;
        }
        if external {
            // Do not start a second driver on the same OpenCR port.
            self.next_start = now + DISCOVERY;
            self.description =
                "External drivers detected: monitoring without taking control".into();
            return;
        }
        if now < self.next_start {
            return;
        }
        let mut command = Command::new("ros2");
        command
            .args(["launch", "turtlebot3_bringup", "robot.launch.py"])
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .process_group(0);
        if !config.namespace.is_empty() {
            command.arg(format!("namespace:={}", config.namespace));
        }
        match command.spawn() {
            Ok(child) => {
                self.process = Some(ManagedProcess {
                    group: Pid::from_raw(child.id() as i32),
                    child,
                    started: now,
                    last_alive: now,
                    healthy_since: None,
                    stopping: None,
                });
                self.description = "Bringup started; calibration and discovery in progress".into();
            }
            Err(error) => {
                self.description = format!("Unable to start ros2: {error}");
                self.schedule_retry();
            }
        }
    }

    fn schedule_retry(&mut self) {
        self.next_start = Instant::now() + Duration::from_secs(self.retry_seconds);
        self.description = format!(
            "{}; retrying in {} s",
            self.description, self.retry_seconds
        );
        self.retry_seconds = (self.retry_seconds * 2).min(60);
    }

    pub fn shutdown(&mut self) {
        if let Some(mut process) = self.process.take() {
            let _ = signal_group(process.group, Signal::SIGINT);
            thread::sleep(STOP_GRACE);
            let _ = signal_group(process.group, Signal::SIGKILL);
            // Bounded even if the kernel does not terminate the process immediately.
            for _ in 0..30 {
                if matches!(process.child.try_wait(), Ok(Some(_))) {
                    break;
                }
                thread::sleep(Duration::from_millis(100));
            }
        }
    }
}

impl Drop for Supervisor {
    fn drop(&mut self) {
        if let Some(process) = &mut self.process {
            let _ = signal_group(process.group, Signal::SIGKILL);
            let _ = process.child.try_wait();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(autostart: bool) -> Config {
        Config {
            bind: "127.0.0.1:8000".into(),
            namespace: String::new(),
            velocity_topic: "/cmd_vel".into(),
            odometry_topic: "/odom".into(),
            sensor_topic: "/sensor_state".into(),
            battery_topic: "/battery_state".into(),
            imu_topic: "/imu".into(),
            scan_topic: "/scan".into(),
            magnetic_topic: "/magnetic_field".into(),
            joint_topic: "/joint_states".into(),
            sound_service: "/sound".into(),
            motor_power_service: "/motor_power".into(),
            reset_service: "/reset".into(),
            stamped: true,
            autostart,
            max_speed: 0.10,
        }
    }

    #[test]
    fn never_spawn_over_an_existing_driver() {
        let mut supervisor = Supervisor::new();
        supervisor.next_start = Instant::now();
        supervisor.tick(&config(true), false, true, || {
            panic!("Stopping external processes is forbidden")
        });
        assert!(supervisor.process.is_none());
        assert!(supervisor.next_start > Instant::now());
        assert!(supervisor.description.contains("External"));
    }

    #[test]
    fn observation_mode_never_starts_ros() {
        let mut supervisor = Supervisor::new();
        supervisor.next_start = Instant::now();
        supervisor.tick(&config(false), false, false, || panic!("Unexpected stop"));
        assert!(supervisor.process.is_none());
        assert!(supervisor.description.contains("disabled"));
    }

    #[test]
    fn repeated_failures_back_off_up_to_sixty_seconds() {
        let mut supervisor = Supervisor::new();
        for _ in 0..10 {
            supervisor.schedule_retry();
        }
        assert_eq!(supervisor.retry_seconds, 60);
        assert!(supervisor.next_start > Instant::now() + Duration::from_secs(59));
    }
}
