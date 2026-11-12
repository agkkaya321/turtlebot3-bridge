//! État partagé de la caméra entre la boucle ROS, le thread d'encodage et HTTP.
//!
//! - la boucle ROS dépose la dernière image brute (`push`), sans jamais attendre ;
//! - le thread d'encodage la convertit, la réduit et la compresse en JPEG ;
//! - HTTP sert la dernière image compressée : une image ancienne n'est jamais
//!   mise en file, le client reçoit toujours la plus récente.
use super::{convert, jpeg};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Condvar, Mutex, MutexGuard,
    },
    time::{Duration, Instant},
};

/// Sans demande HTTP depuis ce délai, la caméra n'est plus lue ni encodée.
pub const IDLE: Duration = Duration::from_secs(5);
/// Une image encodée plus ancienne n'est pas servie comme « nouvelle ».
const STALE: Duration = Duration::from_secs(2);

/// Réglages du flux, modifiables à chaud par `POST /camera/settings`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Settings {
    /// Largeur maximale de l'image envoyée (pixels).
    pub width: u32,
    /// Qualité JPEG (10 à 95).
    pub quality: u8,
    /// Images par seconde au plus.
    pub fps: u32,
    /// Rotation horaire de l'image (0, 90, 180, 270), après réduction.
    pub rotate: u16,
}

/// Changement partiel des réglages.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SettingsPatch {
    width: Option<u32>,
    quality: Option<u8>,
    fps: Option<u32>,
    rotate: Option<u16>,
}

impl Settings {
    pub fn validate(&self) -> Result<(), String> {
        if !(80..=1920).contains(&self.width) {
            return Err("width entre 80 et 1920 pixels".into());
        }
        if !(jpeg::MIN_QUALITY..=jpeg::MAX_QUALITY).contains(&self.quality) {
            return Err(format!("quality entre {} et {}", jpeg::MIN_QUALITY, jpeg::MAX_QUALITY));
        }
        if !(1..=30).contains(&self.fps) {
            return Err("fps entre 1 et 30".into());
        }
        if !matches!(self.rotate, 0 | 90 | 180 | 270) {
            return Err("rotate vaut 0, 90, 180 ou 270".into());
        }
        Ok(())
    }

    pub fn apply(&self, patch: &SettingsPatch) -> Self {
        Self {
            width: patch.width.unwrap_or(self.width),
            quality: patch.quality.unwrap_or(self.quality),
            fps: patch.fps.unwrap_or(self.fps),
            rotate: patch.rotate.unwrap_or(self.rotate),
        }
    }

    pub fn json(&self) -> Value {
        json!({"width": self.width, "quality": self.quality, "fps": self.fps, "rotate": self.rotate})
    }
}

/// Image brute reçue de ROS.
pub struct Raw {
    pub width: usize,
    pub height: usize,
    pub step: usize,
    pub encoding: String,
    pub data: Vec<u8>,
    /// Instant de capture estimé (horodatage du message, sinon réception).
    pub captured: Instant,
}

/// Image compressée prête à servir.
pub struct Frame {
    pub seq: u64,
    pub jpeg: Vec<u8>,
    pub width: usize,
    pub height: usize,
    pub quality: u8,
    pub encode_ms: f64,
    pub captured: Instant,
    pub encoded: Instant,
}

/// Événements par seconde, mesurés sur des fenêtres d'au moins une seconde.
struct Rate {
    window: Instant,
    count: f64,
    value: f64,
}

impl Default for Rate {
    fn default() -> Self {
        Self {
            window: Instant::now(),
            count: 0.0,
            value: 0.0,
        }
    }
}

impl Rate {
    fn add(&mut self, amount: f64) {
        self.roll();
        self.count += amount;
    }

    fn roll(&mut self) {
        let elapsed = self.window.elapsed().as_secs_f64();
        if elapsed >= 1.0 {
            self.value = self.count / elapsed;
            self.count = 0.0;
            self.window = Instant::now();
        }
    }

    fn get(&mut self) -> f64 {
        self.roll();
        (self.value * 10.0).round() / 10.0
    }
}

#[derive(Default)]
struct Stats {
    received: u64,
    encoded: u64,
    served: u64,
    received_rate: Rate,
    encoded_rate: Rate,
    served_rate: Rate,
    served_bytes: Rate,
    source: Option<(usize, usize, String)>,
    subscribed: bool,
    publishers: Option<usize>,
    driver: String,
    error: Option<String>,
}

pub struct Hub {
    pub topic: String,
    raw: Mutex<Option<Raw>>,
    raw_ready: Condvar,
    frame: Mutex<Option<Arc<Frame>>>,
    frame_ready: Condvar,
    settings: Mutex<Settings>,
    demand: Mutex<Option<Instant>>,
    stats: Mutex<Stats>,
    /// Requêtes HTTP en attente d'une image (bornées).
    pub waiting: AtomicUsize,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}

fn millis(duration: Duration) -> f64 {
    (duration.as_secs_f64() * 10_000.0).round() / 10.0
}

impl Hub {
    pub fn new(topic: String, settings: Settings) -> Self {
        Self {
            topic,
            raw: Mutex::new(None),
            raw_ready: Condvar::new(),
            frame: Mutex::new(None),
            frame_ready: Condvar::new(),
            settings: Mutex::new(settings),
            demand: Mutex::new(None),
            stats: Mutex::new(Stats {
                driver: "Initialisation".into(),
                ..Stats::default()
            }),
            waiting: AtomicUsize::new(0),
        }
    }

    /// Un client vient de demander une image : la caméra reste active.
    pub fn demand(&self) {
        *lock(&self.demand) = Some(Instant::now());
    }

    /// Quelqu'un regarde-t-il la caméra ?
    pub fn wanted(&self) -> bool {
        lock(&self.demand).is_some_and(|time| time.elapsed() < IDLE)
    }

    /// Appelé par la boucle ROS : remplace l'image en attente, sans bloquer.
    pub fn push(&self, raw: Raw) {
        {
            let mut stats = lock(&self.stats);
            stats.received += 1;
            stats.received_rate.add(1.0);
            let source = (raw.width, raw.height, raw.encoding.clone());
            if stats.source.as_ref() != Some(&source) {
                stats.source = Some(source);
            }
        }
        *lock(&self.raw) = Some(raw);
        self.raw_ready.notify_one();
    }

    pub fn set_subscription(&self, subscribed: bool, error: Option<String>) {
        let mut stats = lock(&self.stats);
        stats.subscribed = subscribed;
        if error.is_some() || subscribed {
            stats.error = error;
        }
    }

    pub fn set_driver(&self, description: String, publishers: Option<usize>) {
        let mut stats = lock(&self.stats);
        stats.driver = description;
        stats.publishers = publishers;
    }

    pub fn settings(&self) -> Settings {
        *lock(&self.settings)
    }

    pub fn update_settings(&self, patch: &SettingsPatch) -> Result<Settings, String> {
        let mut settings = lock(&self.settings);
        let next = settings.apply(patch);
        next.validate()?;
        *settings = next;
        Ok(next)
    }

    /// Thread d'encodage : attend une image brute, la compresse, la publie.
    pub fn encode_loop(&self, running: &AtomicBool) {
        let mut last_encode: Option<Instant> = None;
        let mut seq = 0u64;
        while running.load(Ordering::SeqCst) {
            let raw = {
                let slot = lock(&self.raw);
                let (mut slot, _) = self
                    .raw_ready
                    .wait_timeout_while(slot, Duration::from_millis(250), |raw| raw.is_none())
                    .unwrap_or_else(|error| error.into_inner());
                slot.take()
            };
            let Some(raw) = raw else { continue };
            if !self.wanted() {
                continue;
            }
            let settings = self.settings();
            // Limite d'images par seconde, avec une marge pour la cadence irrégulière
            // de la boucle ROS (50 ms).
            let interval = Duration::from_secs_f64(0.75 / f64::from(settings.fps));
            if last_encode.is_some_and(|time| time.elapsed() < interval) {
                continue;
            }
            last_encode = Some(Instant::now());
            let started = Instant::now();
            let result = convert::prepare(
                raw.width,
                raw.height,
                raw.step,
                &raw.encoding,
                &raw.data,
                settings.width as usize,
            )
            .map(|picture| convert::rotate(picture, settings.rotate))
            .and_then(|picture| {
                jpeg::encode(&picture.data, picture.width, picture.height, picture.channels, settings.quality)
                    .map(|bytes| (picture.width, picture.height, bytes))
            });
            match result {
                Ok((width, height, bytes)) => {
                    seq += 1;
                    let frame = Frame {
                        seq,
                        jpeg: bytes,
                        width,
                        height,
                        quality: settings.quality,
                        encode_ms: millis(started.elapsed()),
                        captured: raw.captured,
                        encoded: Instant::now(),
                    };
                    {
                        let mut stats = lock(&self.stats);
                        stats.encoded += 1;
                        stats.encoded_rate.add(1.0);
                        stats.error = None;
                    }
                    *lock(&self.frame) = Some(Arc::new(frame));
                    self.frame_ready.notify_all();
                }
                Err(error) => lock(&self.stats).error = Some(error),
            }
        }
    }

    /// Image plus récente que `after`, encodée récemment. Un `after` supérieur
    /// au compteur actuel vient d'un bridge précédent : il est ignoré.
    fn pick(frame: &Option<Arc<Frame>>, after: u64) -> Option<Arc<Frame>> {
        let frame = frame.as_ref()?;
        let after = if after > frame.seq { 0 } else { after };
        (frame.seq > after && frame.encoded.elapsed() < STALE).then(|| frame.clone())
    }

    pub fn latest(&self, after: u64) -> Option<Arc<Frame>> {
        Self::pick(&lock(&self.frame), after)
    }

    /// Attend au plus `timeout` une image plus récente que `after`.
    pub fn wait(&self, after: u64, timeout: Duration) -> Option<Arc<Frame>> {
        let deadline = Instant::now() + timeout;
        let mut guard = lock(&self.frame);
        loop {
            if let Some(frame) = Self::pick(&guard, after) {
                return Some(frame);
            }
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return None;
            }
            guard = self
                .frame_ready
                .wait_timeout(guard, left)
                .unwrap_or_else(|error| error.into_inner())
                .0;
        }
    }

    pub fn served(&self, bytes: usize) {
        let mut stats = lock(&self.stats);
        stats.served += 1;
        stats.served_rate.add(1.0);
        stats.served_bytes.add(bytes as f64);
    }

    pub fn status_json(&self) -> Value {
        let settings = self.settings();
        let frame = lock(&self.frame).clone();
        let wanted = self.wanted();
        let mut stats = lock(&self.stats);
        let kbps = (stats.served_bytes.get() * 8.0 / 1000.0).round();
        json!({
            "topic": self.topic,
            "driver": stats.driver,
            "publishers": stats.publishers,
            "active": wanted,
            "subscribed": stats.subscribed,
            "source": stats.source.as_ref().map(|(w, h, e)| json!({"width": w, "height": h, "encoding": e})),
            "frames": {"received": stats.received, "encoded": stats.encoded, "served": stats.served},
            "fps": {
                "received": stats.received_rate.get(),
                "encoded": stats.encoded_rate.get(),
                "served": stats.served_rate.get(),
            },
            "kbps": kbps,
            "last": frame.map(|f| json!({
                "seq": f.seq,
                "width": f.width,
                "height": f.height,
                "bytes": f.jpeg.len(),
                "quality": f.quality,
                "encode_ms": f.encode_ms,
                "age_ms": f.captured.elapsed().as_millis() as u64,
            })),
            "settings": settings.json(),
            "error": stats.error,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{sync::Arc, thread};

    fn hub() -> Arc<Hub> {
        Arc::new(Hub::new("/image_raw".into(), Settings { width: 80, quality: 60, fps: 30, rotate: 0 }))
    }

    fn raw(width: usize, height: usize) -> Raw {
        Raw {
            width,
            height,
            step: width * 3,
            encoding: "rgb8".into(),
            data: vec![120; width * height * 3],
            captured: Instant::now(),
        }
    }

    #[test]
    fn settings_are_validated() {
        let settings = Settings { width: 480, quality: 60, fps: 15, rotate: 0 };
        assert!(settings.validate().is_ok());
        let patch: SettingsPatch = serde_json::from_str(r#"{"rotate": 45}"#).unwrap();
        assert!(settings.apply(&patch).validate().is_err());
        let patch: SettingsPatch = serde_json::from_str(r#"{"rotate": 270}"#).unwrap();
        assert_eq!(settings.apply(&patch).rotate, 270);
        let patch: SettingsPatch = serde_json::from_str(r#"{"width": 20}"#).unwrap();
        assert!(settings.apply(&patch).validate().is_err());
        let patch: SettingsPatch = serde_json::from_str(r#"{"quality": 99}"#).unwrap();
        assert!(settings.apply(&patch).validate().is_err());
        assert!(serde_json::from_str::<SettingsPatch>(r#"{"bitrate": 1}"#).is_err());
    }

    #[test]
    fn frames_are_encoded_only_while_someone_watches() {
        let hub = hub();
        let running = Arc::new(AtomicBool::new(true));
        let worker = {
            let (hub, running) = (hub.clone(), running.clone());
            thread::spawn(move || hub.encode_loop(&running))
        };
        hub.push(raw(128, 96));
        assert!(hub.wait(0, Duration::from_millis(400)).is_none(), "encodé sans spectateur");

        hub.demand();
        hub.push(raw(128, 96));
        let frame = hub.wait(0, Duration::from_secs(2)).expect("aucune image encodée");
        assert_eq!((frame.width, frame.height), (80, 60));
        assert_eq!(&frame.jpeg[..2], &[0xFF, 0xD8]);
        // Rien de plus récent : l'attente expire.
        assert!(hub.wait(frame.seq, Duration::from_millis(100)).is_none());
        // Un compteur venant d'un ancien bridge est ignoré.
        assert_eq!(hub.latest(frame.seq + 100).map(|f| f.seq), Some(frame.seq));

        // Webcam montée en portrait : 128×96 -> 80×60 -> rotation -> 60×80.
        let patch: SettingsPatch = serde_json::from_str(r#"{"rotate": 90}"#).unwrap();
        hub.update_settings(&patch).unwrap();
        hub.push(raw(128, 96));
        let next = hub.wait(frame.seq, Duration::from_secs(2)).expect("image suivante");
        assert_eq!((next.width, next.height), (60, 80));
        let status = hub.status_json();
        assert_eq!(status["frames"]["received"], 3);
        assert_eq!(status["frames"]["encoded"], 2);
        assert_eq!(status["source"]["encoding"], "rgb8");

        running.store(false, Ordering::SeqCst);
        worker.join().unwrap();
    }

    #[test]
    fn a_broken_image_is_reported_not_fatal() {
        let hub = hub();
        let running = Arc::new(AtomicBool::new(true));
        let worker = {
            let (hub, running) = (hub.clone(), running.clone());
            thread::spawn(move || hub.encode_loop(&running))
        };
        hub.demand();
        let mut broken = raw(8, 8);
        broken.encoding = "32FC1".into();
        hub.push(broken);
        thread::sleep(Duration::from_millis(300));
        assert!(hub.status_json()["error"].as_str().unwrap().contains("32FC1"));
        hub.push(raw(8, 8));
        assert!(hub.wait(0, Duration::from_secs(2)).is_some());
        assert!(hub.status_json()["error"].is_null());
        running.store(false, Ordering::SeqCst);
        worker.join().unwrap();
    }
}
