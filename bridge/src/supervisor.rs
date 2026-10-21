//! Supervision du seul groupe de processus lancé par ce bridge (Linux).
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
            description: "Découverte des pilotes existants".into(),
        }
    }

    pub fn allows_motion(&self) -> bool {
        self.process.as_ref().is_none_or(|p| p.stopping.is_none())
    }

    /// Appelé à chaque cycle. Aucun wait()/sleep() bloquant pendant la conduite.
    /// stop_motion envoie zéro AVANT de terminer un groupe de processus.
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
                    Ok(Some(status)) => Some(format!("Bringup terminé : {status}")),
                    Err(error) => Some(format!("Processus inaccessible : {error}")),
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
                            Some("Données ROS perdues durablement".into())
                        } else {
                            None
                        }
                    }
                };
                if let Some(reason) = failure {
                    stop_motion();
                    process.stopping = Some(now);
                    self.description = format!("{reason} ; arrêt avant relance");
                    if let Err(error) = signal_group(process.group, Signal::SIGINT) {
                        eprintln!("Arrêt du bringup impossible : {error}");
                    }
                } else {
                    self.description = if ros_alive {
                        "Bringup supervisé actif"
                    } else {
                        "Démarrage du bringup / attente des données"
                    }
                    .into();
                }
            }
            if process
                .stopping
                .is_some_and(|time| time.elapsed() >= STOP_GRACE)
            {
                // Terminer aussi les enfants restants si ros2 launch a déjà quitté.
                if let Err(error) = signal_group(process.group, Signal::SIGKILL) {
                    self.description = format!("Nettoyage impossible : {error} ; relance bloquée");
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
            self.description = "Démarrage automatique désactivé".into();
            return;
        }
        if external {
            // Ne pas lancer un deuxième pilote sur le même port OpenCR.
            self.next_start = now + DISCOVERY;
            self.description =
                "Pilotes externes détectés : surveillance sans prise de contrôle".into();
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
                self.description = "Bringup lancé ; calibration et découverte en cours".into();
            }
            Err(error) => {
                self.description = format!("Lancement de ros2 impossible : {error}");
                self.schedule_retry();
            }
        }
    }

    fn schedule_retry(&mut self) {
        self.next_start = Instant::now() + Duration::from_secs(self.retry_seconds);
        self.description = format!(
            "{} ; nouvel essai dans {} s",
            self.description, self.retry_seconds
        );
        self.retry_seconds = (self.retry_seconds * 2).min(60);
    }

    pub fn shutdown(&mut self) {
        if let Some(mut process) = self.process.take() {
            let _ = signal_group(process.group, Signal::SIGINT);
            thread::sleep(STOP_GRACE);
            let _ = signal_group(process.group, Signal::SIGKILL);
            // Borné, même si le noyau ne termine pas immédiatement le processus.
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
            panic!("Arrêt externe interdit")
        });
        assert!(supervisor.process.is_none());
        assert!(supervisor.next_start > Instant::now());
        assert!(supervisor.description.contains("externes"));
    }

    #[test]
    fn observation_mode_never_starts_ros() {
        let mut supervisor = Supervisor::new();
        supervisor.next_start = Instant::now();
        supervisor.tick(&config(false), false, false, || panic!("Arrêt inattendu"));
        assert!(supervisor.process.is_none());
        assert!(supervisor.description.contains("désactivé"));
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
