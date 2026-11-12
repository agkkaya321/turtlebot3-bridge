//! Optional camera transport. Its ROS node and HTTP workers never run in the motor loop.
use crate::{state, BridgeResult};
use futures::{FutureExt, StreamExt};
use nix::{
    sys::signal::{killpg, Signal},
    unistd::Pid,
};
use r2r::sensor_msgs::msg::CompressedImage;
use serde_json::{json, Value};
use std::{
    env,
    io::Cursor,
    os::unix::process::CommandExt,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, SyncSender},
        Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
use tiny_http::{Header, Request, Response};

pub const MAX_FRAME_BYTES: usize = 2 * 1024 * 1024;
const MAX_AGE: Duration = Duration::from_secs(1);

#[derive(Clone)]
pub struct Config {
    pub enabled: bool,
    pub autostart: bool,
    pub raw_topic: String,
    pub topic: String,
    pub device: String,
    pub width: u32,
    pub height: u32,
    pub fps: u32,
}

impl Config {
    pub fn from_env(namespace: &str) -> BridgeResult<Self> {
        let flag = |name: &str| -> BridgeResult<bool> {
            match env::var(name).as_deref().unwrap_or("false") {
                "true" => Ok(true),
                "false" => Ok(false),
                _ => Err(format!("{name} must be true or false").into()),
            }
        };
        let number = |name: &str, default: u32, max: u32| -> BridgeResult<u32> {
            let value = env::var(name)
                .unwrap_or(default.to_string())
                .parse::<u32>()?;
            if value == 0 || value > max {
                return Err(format!("{name} must be 1..{max}").into());
            }
            Ok(value)
        };
        let raw_topic = env::var("CAMERA_RAW_TOPIC").unwrap_or_else(|_| {
            if namespace.is_empty() {
                "/image_raw".into()
            } else {
                format!("/{namespace}/image_raw")
            }
        });
        if !raw_topic.starts_with('/')
            || raw_topic.ends_with('/')
            || raw_topic.contains("//")
            || !raw_topic
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '/')
        {
            return Err("CAMERA_RAW_TOPIC must be an absolute ROS topic name".into());
        }
        Ok(Self {
            enabled: flag("CAMERA_ENABLED")?,
            autostart: flag("CAMERA_AUTOSTART")?,
            topic: format!("{raw_topic}/compressed"),
            raw_topic,
            device: env::var("CAMERA_DEVICE").unwrap_or_else(|_| "/dev/video0".into()),
            width: number("CAMERA_WIDTH", 640, 1920)?,
            height: number("CAMERA_HEIGHT", 480, 1080)?,
            fps: number("CAMERA_FPS", 15, 30)?,
        })
    }
}

#[derive(Clone)]
pub struct Frame {
    pub data: Arc<Vec<u8>>,
    pub received: Instant,
    pub sequence: u64,
    pub stamp_sec: i32,
    pub stamp_nanosec: u32,
}

pub struct Camera {
    config: Config,
    frame: Option<Frame>,
    sequence: u64,
    message: String,
    supervisor: String,
}
pub type SharedCamera = Arc<Mutex<Camera>>;

impl Camera {
    pub fn new(config: Config) -> Self {
        Self {
            config,
            frame: None,
            sequence: 0,
            message: "Waiting for JPEG images".into(),
            supervisor: "Not started".into(),
        }
    }

    fn accept(&mut self, message: CompressedImage) {
        let format = message.format.to_ascii_lowercase();
        // Do not accidentally serve PNG, depth transport, empty or oversized payloads as JPEG.
        if (!format.contains("jpeg") && format != "jpg")
            || message.data.len() > MAX_FRAME_BYTES
            || !message.data.starts_with(&[0xff, 0xd8])
            || !message.data.ends_with(&[0xff, 0xd9])
        {
            self.frame = None;
            self.message = "Invalid JPEG or frame larger than 2 MiB".into();
            return;
        }
        self.sequence = self.sequence.wrapping_add(1);
        self.frame = Some(Frame {
            data: Arc::new(message.data),
            received: Instant::now(),
            sequence: self.sequence,
            stamp_sec: message.header.stamp.sec,
            stamp_nanosec: message.header.stamp.nanosec,
        });
        self.message = "Receiving images".into();
    }

    pub fn latest(&self) -> Option<Frame> {
        self.frame
            .as_ref()
            .filter(|f| self.config.enabled && f.received.elapsed() < MAX_AGE)
            .cloned()
    }

    pub fn json(&self) -> Value {
        let state = if !self.config.enabled {
            "disabled"
        } else if self.latest().is_some() {
            "ready"
        } else if self.frame.is_some() {
            "stale"
        } else {
            "waiting"
        };
        json!({"enabled": self.config.enabled, "autostart": self.config.autostart,
            "state": state, "topic": self.config.topic,
            "message": if state == "disabled" { "Camera disabled" } else if state == "stale" {
                "No fresh image for at least 1 s" } else { &self.message },
            "supervisor": self.supervisor, "sequence": self.sequence,
            "age_ms": self.frame.as_ref().map(|f| f.received.elapsed().as_millis() as u64),
            "max_age_ms": MAX_AGE.as_millis() as u64, "max_frame_bytes": MAX_FRAME_BYTES})
    }
}

// Own only the process group we started; an external usb_cam is never terminated.
struct Driver(Child);
impl Driver {
    fn start(config: &Config) -> std::io::Result<Self> {
        Command::new("ros2")
            .args([
                "run",
                "usb_cam",
                "usb_cam_node_exe",
                "--ros-args",
                "-r",
                "__node:=bridge_usb_cam",
                "-r",
                &format!("image_raw:={}", config.raw_topic),
                "-r",
                &format!("image_raw/compressed:={}", config.topic),
                "-r",
                &format!("camera_info:={}/camera_info", config.raw_topic),
                "-p",
                &format!("video_device:={}", config.device),
                "-p",
                "pixel_format:=mjpeg2rgb",
                "-p",
                &format!("image_width:={}", config.width),
                "-p",
                &format!("image_height:={}", config.height),
                "-p",
                &format!("framerate:={}.0", config.fps),
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .process_group(0)
            .spawn()
            .map(Self)
    }
}
impl Drop for Driver {
    fn drop(&mut self) {
        let group = Pid::from_raw(self.0.id() as i32);
        let _ = killpg(group, Signal::SIGINT);
        // Independent camera thread: never hold shared state or delay the motor loop here.
        thread::sleep(Duration::from_secs(1));
        let _ = killpg(group, Signal::SIGKILL);
        for _ in 0..20 {
            if matches!(self.0.try_wait(), Ok(Some(_))) {
                break;
            }
            thread::sleep(Duration::from_millis(50));
        }
    }
}

fn receive(config: &Config, shared: &SharedCamera, running: &AtomicBool) -> BridgeResult<()> {
    let context = r2r::Context::create()?;
    let mut node = r2r::Node::create(context, "turtlebot_camera_bridge", "")?;
    let mut qos = r2r::QosProfile::sensor_data();
    qos.depth = 1;
    let mut images = node.subscribe::<CompressedImage>(&config.topic, qos)?;
    let mut driver: Option<Driver> = None;
    let mut next_start = Instant::now() + Duration::from_secs(5);
    let mut next_graph = Instant::now();
    let mut last_frame = Instant::now();
    let mut retry = 2;
    while running.load(Ordering::SeqCst) {
        node.spin_once(Duration::from_millis(10));
        // Bounded drain, keeping only the most recent image.
        let mut latest = None;
        for _ in 0..4 {
            match images.next().now_or_never() {
                Some(Some(image)) => latest = Some(image),
                _ => break,
            }
        }
        if let Some(image) = latest {
            let mut camera = state::lock(shared);
            camera.accept(image);
            if camera.latest().is_some() {
                last_frame = Instant::now();
            }
        }
        if Instant::now() < next_graph {
            continue;
        }
        next_graph = Instant::now() + Duration::from_secs(1);
        if let Some(owned) = &mut driver {
            let failed = !matches!(owned.0.try_wait(), Ok(None));
            if failed || last_frame.elapsed() > Duration::from_secs(10) {
                {
                    let mut camera = state::lock(shared);
                    camera.frame = None;
                    camera.supervisor = "Camera driver stopped or stalled; retrying".into();
                }
                drop(driver.take());
                next_start = Instant::now() + Duration::from_secs(retry);
                retry = (retry * 2).min(30);
            } else if last_frame.elapsed() < MAX_AGE {
                state::lock(shared).supervisor = "Supervised camera active".into();
            }
            continue;
        }
        if !config.autostart {
            state::lock(shared).supervisor = "Automatic camera startup disabled".into();
            continue;
        }
        // Raw publisher matters too: missing compression plugins must not cause a second capture.
        let external = !node
            .get_publishers_info_by_topic(&config.topic, false)?
            .is_empty()
            || !node
                .get_publishers_info_by_topic(&config.raw_topic, false)?
                .is_empty();
        if external {
            next_start = Instant::now() + Duration::from_secs(5);
            state::lock(shared).supervisor = "External camera detected; monitoring only".into();
        } else if Instant::now() >= next_start {
            match Driver::start(config) {
                Ok(child) => {
                    driver = Some(child);
                    last_frame = Instant::now();
                    state::lock(shared).supervisor = "Starting usb_cam".into();
                }
                Err(error) => {
                    state::lock(shared).supervisor = format!("Cannot start usb_cam: {error}");
                    next_start = Instant::now() + Duration::from_secs(retry);
                    retry = (retry * 2).min(30);
                }
            }
        }
    }
    Ok(())
}

pub fn start(shared: SharedCamera, running: Arc<AtomicBool>) -> Option<JoinHandle<()>> {
    let config = state::lock(&shared).config.clone();
    if !config.enabled {
        return None;
    }
    Some(thread::spawn(move || {
        while running.load(Ordering::SeqCst) {
            if let Err(error) = receive(&config, &shared, &running) {
                let mut camera = state::lock(&shared);
                camera.frame = None;
                camera.message = format!("Camera ROS error: {error}");
                eprintln!("{}", camera.message);
            }
            for _ in 0..20 {
                if !running.load(Ordering::SeqCst) {
                    break;
                }
                thread::sleep(Duration::from_millis(100));
            }
        }
        state::lock(&shared).frame = None;
    }))
}

/// A small separate pool: slow image downloads cannot consume the control HTTP workers.
pub fn http_workers(shared: SharedCamera, running: Arc<AtomicBool>) -> SyncSender<Request> {
    let (sender, receiver) = mpsc::sync_channel::<Request>(2);
    let receiver = Arc::new(Mutex::new(receiver));
    for _ in 0..2 {
        let (receiver, shared, running) = (receiver.clone(), shared.clone(), running.clone());
        thread::spawn(move || {
            while running.load(Ordering::SeqCst) {
                let request = state::lock(&receiver).recv_timeout(Duration::from_millis(100));
                let Ok(request) = request else {
                    continue;
                };
                let frame = state::lock(&shared).latest();
                if let Some(frame) = frame {
                    let headers = vec![
                        Header::from_bytes("Content-Type", "image/jpeg").unwrap(),
                        Header::from_bytes("Cache-Control", "no-store").unwrap(),
                        Header::from_bytes("X-Camera-Sequence", frame.sequence.to_string())
                            .unwrap(),
                        Header::from_bytes(
                            "X-Camera-Age-Ms",
                            frame.received.elapsed().as_millis().to_string(),
                        )
                        .unwrap(),
                        Header::from_bytes(
                            "X-Camera-Stamp",
                            format!("{}.{:09}", frame.stamp_sec, frame.stamp_nanosec),
                        )
                        .unwrap(),
                    ];
                    let length = frame.data.len();
                    // Clone only in this worker, never while holding the camera mutex.
                    let response = Response::new(
                        200.into(),
                        headers,
                        Cursor::new(frame.data.as_ref().clone()),
                        Some(length),
                        None,
                    );
                    let _ = request.respond(response);
                } else {
                    let response = Response::from_string(
                        json!({"error": "Camera disabled or no fresh JPEG image"}).to_string(),
                    )
                    .with_status_code(503)
                    .with_header(Header::from_bytes("Content-Type", "application/json").unwrap())
                    .with_header(Header::from_bytes("Cache-Control", "no-store").unwrap());
                    let _ = request.respond(response);
                }
            }
        });
    }
    sender
}

#[cfg(test)]
mod tests {
    use super::*;
    fn camera() -> Camera {
        Camera::new(Config {
            enabled: true,
            autostart: false,
            raw_topic: "/image_raw".into(),
            topic: "/image_raw/compressed".into(),
            device: "/dev/video0".into(),
            width: 640,
            height: 480,
            fps: 15,
        })
    }
    fn jpeg() -> CompressedImage {
        CompressedImage {
            format: "rgb8; jpeg compressed bgr8".into(),
            data: vec![0xff, 0xd8, 0xff, 0xd9],
            ..Default::default()
        }
    }
    #[test]
    fn missing_stale_and_disabled_frames_are_not_served() {
        let mut camera = camera();
        assert!(camera.latest().is_none());
        camera.accept(jpeg());
        assert!(camera.latest().is_some());
        camera.frame.as_mut().unwrap().received = Instant::now() - Duration::from_secs(2);
        assert!(camera.latest().is_none());
        assert_eq!(camera.json()["state"], "stale");
        camera.accept(jpeg());
        camera.config.enabled = false;
        assert!(camera.latest().is_none());
    }
    #[test]
    fn invalid_images_clear_previous_frame_and_memory_is_bounded() {
        let mut camera = camera();
        camera.accept(jpeg());
        let mut bad = jpeg();
        bad.format = "png".into();
        camera.accept(bad);
        assert!(camera.latest().is_none());
        let mut large = jpeg();
        large.data = vec![0; MAX_FRAME_BYTES + 1];
        camera.accept(large);
        assert!(camera.latest().is_none());
        camera.accept(jpeg());
        camera.accept(jpeg());
        assert_eq!(camera.latest().unwrap().sequence, 3);
    }
}
