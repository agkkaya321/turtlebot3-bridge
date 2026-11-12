//! Lance le pilote usb_cam (paquet ros-jazzy-usb-cam, déjà installé sur le robot)
//! quand aucun nœud ne publie l'image, et le relance s'il s'arrête.
//! Indépendant du superviseur du bringup : la conduite n'en dépend jamais.
use nix::{
    errno::Errno,
    sys::signal::{killpg, Signal},
    unistd::Pid,
};
use std::{
    os::unix::process::CommandExt,
    path::Path,
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

/// Laisser DDS découvrir un pilote déjà lancé avant d'en démarrer un.
const DISCOVERY: Duration = Duration::from_secs(5);
const STOP_GRACE: Duration = Duration::from_secs(3);
/// Délai avant de revérifier la présence de la webcam.
const DEVICE_RETRY: Duration = Duration::from_secs(5);
/// Nom du nœud usb_cam lancé par le bridge.
pub const NODE_NAME: &str = "tb3_bridge_camera";
/// Nom donné par ROS à un publisher dont le nœud a disparu du graphe.
const UNKNOWN_NODE: &str = "_NODE_NAME_UNKNOWN_";
/// Un publisher d'un nœud mort sans prévenir reste visible jusqu'à
/// l'expiration de son bail DDS (20 s par défaut avec Fast DDS).
const GHOST: Duration = Duration::from_secs(30);

/// Nom court d'un nœud (« /ns/nom » -> « nom »).
fn short_name(full: &str) -> &str {
    full.rsplit('/').next().unwrap_or(full)
}

#[derive(Clone, Debug)]
pub struct DriverConfig {
    pub autostart: bool,
    pub device: String,
    pub pixel_format: String,
    pub width: u32,
    pub height: u32,
    pub fps: f64,
    pub topic: String,
    pub namespace: String,
}

impl DriverConfig {
    /// Arguments de `ros2 run usb_cam usb_cam_node_exe`.
    pub fn arguments(&self) -> Vec<String> {
        let mut arguments: Vec<String> = [
            "run",
            "usb_cam",
            "usb_cam_node_exe",
            "--ros-args",
        ]
        .map(String::from)
        .to_vec();
        arguments.extend(["-r".into(), format!("__node:={NODE_NAME}")]);
        if !self.namespace.is_empty() {
            arguments.extend(["-r".into(), format!("__ns:=/{}", self.namespace)]);
        }
        for parameter in [
            format!("video_device:={}", self.device),
            format!("pixel_format:={}", self.pixel_format),
            format!("image_width:={}", self.width),
            format!("image_height:={}", self.height),
            // framerate est un double dans usb_cam : « 15 » serait refusé.
            format!("framerate:={:.1}", self.fps),
        ] {
            arguments.extend(["-p".into(), parameter]);
        }
        arguments.extend(["-r".into(), format!("image_raw:={}", self.topic)]);
        arguments
    }
}

struct Process {
    child: Child,
    group: Pid,
    started: Instant,
    stopping: Option<Instant>,
}

pub struct Driver {
    process: Option<Process>,
    /// Fin du dernier usb_cam lancé par le bridge.
    last_exit: Option<Instant>,
    next_start: Instant,
    retry_seconds: u64,
    pub description: String,
}

fn signal_group(group: Pid, signal: Signal) {
    match killpg(group, signal) {
        Ok(()) | Err(Errno::ESRCH) => {}
        Err(error) => eprintln!("Signal au pilote caméra impossible : {error}"),
    }
}

impl Driver {
    pub fn new() -> Self {
        Self {
            process: None,
            last_exit: None,
            next_start: Instant::now() + DISCOVERY,
            retry_seconds: 2,
            description: "Recherche d'une caméra déjà publiée".into(),
        }
    }

    /// Appelé une fois par seconde par la boucle ROS ; ne bloque jamais.
    /// `publishers` : nœuds qui publient le topic de l'image (« /ns/nom »).
    pub fn tick(&mut self, config: &DriverConfig, publishers: &[String]) {
        let now = Instant::now();
        let ours = publishers.iter().any(|name| short_name(name) == NODE_NAME);
        // Un usb_cam du bridge qui vient de planter reste visible ~20 s dans le
        // graphe DDS, sous son nom puis comme nœud inconnu : ce n'est pas une
        // autre caméra, il ne doit pas empêcher la relance.
        let ghosts = self.last_exit.is_some_and(|time| time.elapsed() < GHOST);
        let other = publishers.iter().find(|name| {
            let short = short_name(name);
            short != NODE_NAME && !(ghosts && short == UNKNOWN_NODE)
        });
        if let Some(process) = &mut self.process {
            if process.stopping.is_some() {
                return;
            }
            match process.child.try_wait() {
                Ok(None) => {
                    if process.started.elapsed() >= Duration::from_secs(60) {
                        self.retry_seconds = 2;
                    }
                    self.description = if ours {
                        format!("usb_cam lancé par le bridge (PID {})", process.child.id())
                    } else {
                        format!("usb_cam démarre (PID {}), pas encore d'image", process.child.id())
                    };
                }
                exit => {
                    // Terminer d'éventuels enfants restés dans le groupe.
                    signal_group(process.group, Signal::SIGKILL);
                    let _ = process.child.try_wait();
                    self.process = None;
                    self.last_exit = Some(now);
                    self.description = match exit {
                        Ok(Some(status)) => format!("usb_cam arrêté ({status}) : voir bridge.log"),
                        Err(error) => format!("usb_cam inaccessible : {error}"),
                        Ok(None) => unreachable!(),
                    };
                    self.schedule_retry();
                }
            }
            return;
        }
        if let Some(name) = other {
            // usb_cam ouvre la webcam en exclusivité : ne pas en lancer un second.
            self.next_start = now + DISCOVERY;
            self.description = format!("Caméra publiée par le nœud {name}");
            return;
        }
        if !config.autostart {
            self.description = "Démarrage automatique désactivé (CAMERA_AUTOSTART=false)".into();
            return;
        }
        if now < self.next_start {
            return;
        }
        if !Path::new(&config.device).exists() {
            self.next_start = now + DEVICE_RETRY;
            self.description = format!("Aucune webcam sur {} : brancher la caméra USB", config.device);
            return;
        }
        let mut command = Command::new("ros2");
        command
            .args(config.arguments())
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .process_group(0);
        match command.spawn() {
            Ok(child) => {
                self.description = format!("usb_cam lancé (PID {})", child.id());
                self.process = Some(Process {
                    group: Pid::from_raw(child.id() as i32),
                    child,
                    started: now,
                    stopping: None,
                });
            }
            Err(error) => {
                self.description = format!("Lancement de ros2 impossible : {error}");
                self.schedule_retry();
            }
        }
    }

    fn schedule_retry(&mut self) {
        self.next_start = Instant::now() + Duration::from_secs(self.retry_seconds);
        self.description = format!("{} ; nouvel essai dans {} s", self.description, self.retry_seconds);
        self.retry_seconds = (self.retry_seconds * 2).min(60);
    }

    /// Demande l'arrêt (SIGINT) sans attendre, en même temps que le bringup.
    pub fn interrupt(&mut self) {
        if let Some(process) = &mut self.process {
            if process.stopping.is_none() {
                signal_group(process.group, Signal::SIGINT);
                process.stopping = Some(Instant::now());
            }
        }
    }

    /// Attend la fin (3 s au plus depuis `interrupt`), puis force l'arrêt.
    pub fn shutdown(&mut self) {
        self.interrupt();
        let Some(mut process) = self.process.take() else {
            return;
        };
        let since = process.stopping.unwrap_or_else(Instant::now);
        while since.elapsed() < STOP_GRACE {
            if matches!(process.child.try_wait(), Ok(Some(_))) {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        signal_group(process.group, Signal::SIGKILL);
        for _ in 0..30 {
            if matches!(process.child.try_wait(), Ok(Some(_))) {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
    }
}

impl Drop for Driver {
    fn drop(&mut self) {
        if let Some(process) = &mut self.process {
            signal_group(process.group, Signal::SIGKILL);
            let _ = process.child.try_wait();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(autostart: bool, device: &str) -> DriverConfig {
        DriverConfig {
            autostart,
            device: device.into(),
            pixel_format: "mjpeg2rgb".into(),
            width: 640,
            height: 480,
            fps: 15.0,
            topic: "/image_raw".into(),
            namespace: String::new(),
        }
    }

    #[test]
    fn arguments_match_the_course_guide() {
        let mut cfg = config(true, "/dev/video0");
        let line = cfg.arguments().join(" ");
        assert!(line.starts_with("run usb_cam usb_cam_node_exe --ros-args"));
        assert!(line.contains("-p pixel_format:=mjpeg2rgb"));
        assert!(line.contains("-p framerate:=15.0"));
        assert!(line.contains("-r image_raw:=/image_raw"));
        assert!(!line.contains("__ns"));
        cfg.namespace = "robot1".into();
        assert!(cfg.arguments().join(" ").contains("-r __ns:=/robot1"));
    }

    #[test]
    fn never_starts_over_an_existing_camera_or_without_device() {
        let mut driver = Driver::new();
        driver.next_start = Instant::now();
        driver.tick(&config(true, "/dev/video0"), &["/my_usb_cam".into()]);
        assert!(driver.process.is_none());
        assert!(driver.description.contains("/my_usb_cam"));

        driver.next_start = Instant::now();
        driver.tick(&config(true, "/dev/inexistant_video"), &[]);
        assert!(driver.process.is_none());
        assert!(driver.description.contains("Aucune webcam"));

        driver.tick(&config(false, "/dev/video0"), &[]);
        assert!(driver.description.contains("désactivé"));
    }

    #[test]
    fn the_ghost_of_our_crashed_driver_does_not_block_a_restart() {
        let mut driver = Driver::new();
        driver.next_start = Instant::now();
        // Publisher fantôme de notre usb_cam mort : on passe à la vérification du périphérique.
        driver.tick(&config(true, "/dev/inexistant_video"), &[format!("/robot1/{NODE_NAME}")]);
        assert!(driver.description.contains("Aucune webcam"), "{}", driver.description);
        // Nœud inconnu : fantôme juste après la fin de notre usb_cam, sinon une vraie caméra.
        let unknown = vec![format!("_NODE_NAMESPACE_UNKNOWN_/{UNKNOWN_NODE}")];
        driver.next_start = Instant::now();
        driver.tick(&config(true, "/dev/inexistant_video"), &unknown);
        assert!(driver.description.contains("publiée"), "{}", driver.description);
        driver.last_exit = Some(Instant::now());
        driver.next_start = Instant::now();
        driver.tick(&config(true, "/dev/inexistant_video"), &unknown);
        assert!(driver.description.contains("Aucune webcam"), "{}", driver.description);
    }
}
