//! Caméra USB du robot, en modules indépendants de la conduite :
//!
//! | Fichier      | Rôle                                                          |
//! |--------------|---------------------------------------------------------------|
//! | `driver.rs`  | lance / relance `usb_cam` si aucune caméra n'est publiée      |
//! | `convert.rs` | encodages ROS -> RVB, réduction de taille par moyenne de zone |
//! | `jpeg.rs`    | encodeur JPEG baseline 4:2:0 écrit pour le bridge             |
//! | `hub.rs`     | dernière image brute / compressée, réglages, statistiques     |
//! | `http.rs`    | `GET /camera/frame`, `/camera/status`, `POST /camera/settings`|
//!
//! La boucle ROS ne fait que déposer la dernière image : la compression
//! tourne dans son propre thread, et aucune erreur caméra ne remonte
//! jusqu'à la boucle de conduite.
mod convert;
mod driver;
mod hub;
pub mod http;
mod jpeg;

pub use hub::Hub;

use driver::{Driver, DriverConfig};
use futures::Stream;
use hub::{Raw, Settings};
use r2r::sensor_msgs::msg::Image;
use std::{
    env,
    str::FromStr,
    sync::{atomic::AtomicBool, Arc},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

/// Vérification du pilote et des publishers : une fois par seconde (20 cycles).
const DRIVER_EVERY: u32 = 20;
const SUBSCRIBE_RETRY: Duration = Duration::from_secs(1);

type Images = Box<dyn Stream<Item = Image> + Unpin>;

pub struct Camera {
    hub: Arc<Hub>,
    driver: Driver,
    driver_config: DriverConfig,
    stream: Option<Images>,
    retry_at: Option<Instant>,
    encoder: Option<JoinHandle<()>>,
}

/// Lecture tolérante : une valeur invalide garde le défaut, la conduite démarre quand même.
fn setting<T: FromStr>(name: &str, default: T, valid: impl Fn(&T) -> bool) -> T {
    match env::var(name) {
        Err(_) => default,
        Ok(text) => match text.trim().parse::<T>() {
            Ok(value) if valid(&value) => value,
            _ => {
                eprintln!("{name}={text} invalide : valeur par défaut utilisée");
                default
            }
        },
    }
}

fn size(name: &str, default: (u32, u32)) -> (u32, u32) {
    let Ok(text) = env::var(name) else {
        return default;
    };
    let parsed = text
        .trim()
        .split_once('x')
        .and_then(|(w, h)| Some((w.parse().ok()?, h.parse().ok()?)))
        .filter(|&(w, h): &(u32, u32)| (16..=4096).contains(&w) && (16..=4096).contains(&h));
    parsed.unwrap_or_else(|| {
        eprintln!("{name}={text} invalide (ex. 1280x720) : {}x{} utilisé", default.0, default.1);
        default
    })
}

impl Camera {
    /// Configuration par variables d'environnement (`robot.env`), toutes facultatives.
    pub fn from_env(namespace: &str, running: Arc<AtomicBool>) -> Self {
        let default_topic = if namespace.is_empty() {
            "/image_raw".to_string()
        } else {
            format!("/{namespace}/image_raw")
        };
        let topic = match env::var("CAMERA_TOPIC") {
            Ok(topic) if crate::http::valid_topic(&topic) => topic,
            Ok(topic) => {
                eprintln!("CAMERA_TOPIC={topic} invalide : {default_topic} utilisé");
                default_topic
            }
            Err(_) => default_topic,
        };
        // 16:9 : toute la largeur du capteur des webcams HD (BRIO 105, C270…) ;
        // un mode 4:3 comme 640x480 en recadre souvent les côtés.
        let (width, height) = size("CAMERA_SOURCE_SIZE", (1280, 720));
        let driver_config = DriverConfig {
            autostart: setting("CAMERA_AUTOSTART", true, |_| true),
            device: env::var("CAMERA_DEVICE").unwrap_or_else(|_| "/dev/video0".into()),
            pixel_format: env::var("CAMERA_PIXEL_FORMAT").unwrap_or_else(|_| "mjpeg2rgb".into()),
            width,
            height,
            fps: setting("CAMERA_SOURCE_FPS", 15.0, |fps| (1.0..=60.0).contains(fps)),
            topic: topic.clone(),
            namespace: namespace.to_string(),
        };
        let defaults = Settings { width: 480, quality: 60, fps: 15, rotate: 0 };
        let mut settings = Settings {
            width: setting("CAMERA_WIDTH", defaults.width, |_| true),
            quality: setting("CAMERA_QUALITY", defaults.quality, |_| true),
            fps: setting("CAMERA_FPS", defaults.fps, |_| true),
            rotate: setting("CAMERA_ROTATE", defaults.rotate, |_| true),
        };
        if let Err(error) = settings.validate() {
            eprintln!("Réglages caméra invalides ({error}) : valeurs par défaut utilisées");
            settings = defaults;
        }
        let hub = Arc::new(Hub::new(topic, settings));
        let encoder = {
            let hub = hub.clone();
            thread::Builder::new()
                .name("camera-encoder".into())
                .spawn(move || hub.encode_loop(&running))
                .map_err(|error| eprintln!("Thread d'encodage caméra impossible : {error}"))
                .ok()
        };
        Self {
            hub,
            driver: Driver::new(),
            driver_config,
            stream: None,
            retry_at: None,
            encoder,
        }
    }

    pub fn hub(&self) -> Arc<Hub> {
        self.hub.clone()
    }

    pub fn describe(&self) -> String {
        let s = self.hub.settings();
        let c = &self.driver_config;
        format!(
            "Caméra {} (usb_cam auto : {}, {} {}x{}) -> JPEG {} px, qualité {}, {} i/s max, rotation {}°",
            self.hub.topic, c.autostart, c.device, c.width, c.height, s.width, s.quality, s.fps, s.rotate
        )
    }

    /// Oublie l'abonnement : le nœud ROS va être recréé.
    pub fn detach(&mut self) {
        if self.stream.take().is_some() {
            self.hub.set_subscription(false, None);
        }
    }

    /// Un cycle de la boucle ROS. Ne renvoie jamais d'erreur à la conduite.
    pub fn tick(&mut self, node: &mut r2r::Node, cycle: u32) {
        if !self.hub.wanted() {
            // Personne ne regarde : ne plus recevoir ~2,7 Mo par image (1280×720 rgb8).
            self.detach();
        } else if self.stream.is_none() && self.retry_at.is_none_or(|time| Instant::now() >= time) {
            let mut qos = r2r::QosProfile::sensor_data();
            qos.depth = 1;
            match node.subscribe::<Image>(&self.hub.topic, qos) {
                Ok(stream) => {
                    self.stream = Some(Box::new(stream));
                    self.retry_at = None;
                    self.hub.set_subscription(true, None);
                }
                Err(error) => {
                    self.retry_at = Some(Instant::now() + SUBSCRIBE_RETRY);
                    let message = format!("Abonnement à {} impossible : {error}", self.hub.topic);
                    self.hub.set_subscription(false, Some(message));
                }
            }
        }
        if let Some(stream) = &mut self.stream {
            if let Some(image) = crate::ros::latest(stream) {
                let captured = crate::health::sample_time(&image.header.stamp).unwrap_or_else(Instant::now);
                self.hub.push(Raw {
                    width: image.width as usize,
                    height: image.height as usize,
                    step: image.step as usize,
                    encoding: image.encoding,
                    data: image.data,
                    captured,
                });
            }
        }
        if cycle % DRIVER_EVERY == 0 {
            let publishers: Option<Vec<String>> = node
                .get_publishers_info_by_topic(&self.hub.topic, false)
                .map(|list| {
                    list.into_iter()
                        .map(|p| format!("{}/{}", p.node_namespace.trim_end_matches('/'), p.node_name))
                        .collect()
                })
                .ok();
            self.driver.tick(&self.driver_config, publishers.as_deref().unwrap_or(&[]));
            self.hub.set_driver(self.driver.description.clone(), publishers.map(|list| list.len()));
        }
    }

    /// Arrêt demandé au pilote, en même temps qu'au bringup.
    pub fn interrupt(&mut self) {
        self.driver.interrupt();
    }

    /// Fin du pilote et du thread d'encodage (`running` doit déjà valoir false).
    pub fn shutdown(&mut self) {
        self.stream = None;
        self.driver.shutdown();
        if let Some(encoder) = self.encoder.take() {
            let _ = encoder.join();
        }
    }
}
