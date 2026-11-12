//! HTTP API, separate from the ROS loop and supervision.
use crate::{
    camera::{self, Hub},
    config::{LEASE, PERIOD, SERVICE_TIMEOUT},
    state::{self, Command, Request as RosRequest, SharedStatus, SharedTelemetry},
    velocity::Velocity,
    BridgeResult,
};
use serde::{de::DeserializeOwned, Deserialize};
use serde_json::{json, Value};
use std::{
    io::Read,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, SyncSender},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};
use tiny_http::{Header, Method, Request, Response, Server, StatusCode};

const MAX_BODY: usize = 512;
/// HTTP readers: the UI polls status while a service response is pending.
const READERS: usize = 4;
const ROUTES: &str = "GET /ready /status /telemetry /topics ; POST /speed /velocity /wheels \
                      /stop /motor_power /sound /reset /watch /unwatch ; caméra : GET /camera/frame \
                      /camera/status ; POST /camera/settings";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SpeedRequest {
    speed_mps: f64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct VelocityRequest {
    linear_mps: f64,
    #[serde(default)]
    angular_rad_s: f64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WheelsRequest {
    left_mps: f64,
    right_mps: f64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MotorPowerRequest {
    enabled: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SoundRequest {
    value: u8,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TopicRequest {
    topic: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Empty {}

#[derive(Clone)]
struct Shared {
    commands: SyncSender<Command>,
    status: SharedStatus,
    telemetry: SharedTelemetry,
    camera: Arc<Hub>,
    max_speed: f64,
    max_angular: f64,
}

pub(crate) fn respond(request: Request, status: u16, body: Value) {
    let header = Header::from_bytes("Content-Type", "application/json").unwrap();
    let response = Response::from_string(body.to_string())
        .with_status_code(StatusCode(status))
        .with_header(Header::from_bytes("Cache-Control", "no-store").unwrap())
        .with_header(header);
    // Losing the client never interrupts the ROS loop or its timeout.
    let _ = request.respond(response);
}

/// Corps JSON borné ; un corps vide vaut `{}`.
pub(crate) fn body<T: DeserializeOwned>(request: &mut Request) -> Result<T, String> {
    if request.body_length().unwrap_or(0) > MAX_BODY {
        return Err("Request body too large".into());
    }
    let mut bytes = Vec::new();
    let read = request
        .as_reader()
        .take((MAX_BODY + 1) as u64)
        .read_to_end(&mut bytes);
    if read.is_err() || bytes.len() > MAX_BODY {
        return Err("Invalid request body".into());
    }
    if bytes.iter().all(u8::is_ascii_whitespace) {
        bytes = b"{}".to_vec();
    }
    serde_json::from_slice(&bytes).map_err(|error| format!("Invalid JSON: {error}"))
}

pub(crate) fn valid_topic(topic: &str) -> bool {
    topic.starts_with('/')
        && topic.len() <= 200
        && topic
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '/')
}

/// Forward a request to the ROS loop and wait for its response.
fn forward(
    shared: &Shared,
    request: RosRequest,
    received_at: Instant,
    wait: Duration,
) -> Result<String, (u16, String)> {
    let (reply, response) = mpsc::sync_channel(1);
    let command = Command {
        request,
        received_at,
        reply,
    };
    // Bounded queue: do not accumulate stale motion commands.
    if shared.commands.try_send(command).is_err() {
        return Err((503, "ROS loop busy or stopped".into()));
    }
    match response.recv_timeout(wait) {
        Ok(Ok(message)) => Ok(message),
        Ok(Err(error)) => Err((503, error)),
        Err(_) => Err((503, "ROS acknowledgement timed out".into())),
    }
}

fn motion(
    shared: &Shared,
    request: Request,
    velocity: Velocity,
    received_at: Instant,
    legacy: bool,
) {
    if let Err(error) = velocity.validate(shared.max_speed) {
        respond(request, 400, json!({ "error": error }));
        return;
    }
    if !velocity.is_zero() && !state::lock(&shared.status).is_ready() {
        respond(request, 503, json!({"error": "not ready"}));
        return;
    }
    match forward(shared, RosRequest::Velocity(velocity), received_at, LEASE) {
        Ok(_) => {
            let (left, right) = velocity.rounded_wheels();
            let mut body = json!({
                "published_to_ros": true,
                "angular_rad_s": velocity.angular,
                "lease_ms": LEASE.as_millis() as u64
            });
            if legacy {
                body["speed_mps"] = json!(velocity.linear);
            } else {
                body["linear_mps"] = json!(velocity.linear);
                body["left_mps"] = json!(left);
                body["right_mps"] = json!(right);
            }
            respond(request, 200, body);
        }
        Err((code, error)) => respond(request, code, json!({ "error": error })),
    }
}

fn action(shared: &Shared, request: Request, ros_request: RosRequest, received_at: Instant) {
    match forward(
        shared,
        ros_request,
        received_at,
        SERVICE_TIMEOUT + Duration::from_millis(500),
    ) {
        Ok(message) => respond(request, 200, json!({"ok": true, "message": message})),
        Err((code, error)) => respond(request, code, json!({ "error": error })),
    }
}

fn handle_request(mut request: Request, shared: &Shared) {
    let received_at = Instant::now();
    let path = request.url().split('?').next().unwrap_or("").to_string();
    let method = request.method().clone();
    if path.starts_with("/camera/") {
        camera::http::handle(request, &path, &shared.camera);
        return;
    }
    if method == Method::Get {
        match path.as_str() {
            "/ready" => {
                let label = state::lock(&shared.status).label();
                let response = Response::from_string(label)
                    .with_header(
                        Header::from_bytes("Content-Type", "text/plain; charset=utf-8").unwrap(),
                    )
                    .with_header(Header::from_bytes("Cache-Control", "no-store").unwrap());
                let _ = request.respond(response);
            }
            "/status" => {
                let body = state::lock(&shared.status).json();
                respond(request, 200, body);
            }
            "/telemetry" => {
                let body =
                    state::lock(&shared.telemetry).json(shared.max_speed, shared.max_angular);
                respond(request, 200, body);
            }
            "/topics" => {
                let body = state::lock(&shared.telemetry).topics_json();
                respond(request, 200, body);
            }
            _ => respond(request, 404, json!({ "error": ROUTES })),
        }
        return;
    }
    if method != Method::Post {
        respond(request, 405, json!({ "error": ROUTES }));
        return;
    }
    macro_rules! parse {
        ($kind:ty, $message:expr) => {
            match body::<$kind>(&mut request) {
                Ok(input) => input,
                Err(error) => {
                    respond(request, 400, json!({"error": format!("{} ({error})", $message)}));
                    return;
                }
            }
        };
    }
    match path.as_str() {
        "/speed" => {
            let input = parse!(SpeedRequest, "Expected: {\"speed_mps\": number}");
            let velocity = Velocity {
                linear: input.speed_mps,
                angular: 0.0,
            };
            motion(shared, request, velocity, received_at, true);
        }
        "/velocity" => {
            let input = parse!(
                VelocityRequest,
                "Expected: {\"linear_mps\": number, \"angular_rad_s\": number}"
            );
            let velocity = Velocity {
                linear: input.linear_mps,
                angular: input.angular_rad_s,
            };
            motion(shared, request, velocity, received_at, false);
        }
        "/wheels" => {
            let input = parse!(
                WheelsRequest,
                "Expected: {\"left_mps\": number, \"right_mps\": number}"
            );
            let velocity = Velocity::from_wheels(input.left_mps, input.right_mps);
            motion(shared, request, velocity, received_at, false);
        }
        "/stop" => {
            parse!(Empty, "Expected an empty body");
            motion(shared, request, Velocity::ZERO, received_at, false);
        }
        "/motor_power" => {
            let input = parse!(MotorPowerRequest, "Expected: {\"enabled\": true|false}");
            action(
                shared,
                request,
                RosRequest::MotorPower(input.enabled),
                received_at,
            );
        }
        "/sound" => {
            let input = parse!(SoundRequest, "Expected: {\"value\": 0..5}");
            if input.value > 5 {
                respond(request, 400, json!({"error": "Sound must be between 0 and 5"}));
                return;
            }
            action(shared, request, RosRequest::Sound(input.value), received_at);
        }
        "/reset" => {
            parse!(Empty, "Expected an empty body");
            action(shared, request, RosRequest::Reset, received_at);
        }
        "/watch" | "/unwatch" => {
            let input = parse!(TopicRequest, "Expected: {\"topic\": \"/name\"}");
            if !valid_topic(&input.topic) {
                respond(request, 400, json!({"error": "Invalid ROS topic name"}));
                return;
            }
            let ros_request = if path == "/watch" {
                RosRequest::Watch(input.topic)
            } else {
                RosRequest::Unwatch(input.topic)
            };
            action(shared, request, ros_request, received_at);
        }
        _ => respond(request, 404, json!({ "error": ROUTES })),
    }
}

pub fn start(
    bind: &str,
    commands: SyncSender<Command>,
    status: SharedStatus,
    telemetry: SharedTelemetry,
    camera: Arc<Hub>,
    limits: (f64, f64),
    running: Arc<AtomicBool>,
) -> BridgeResult<()> {
    let server = Arc::new(Server::http(bind)?);
    let shared = Shared {
        commands,
        status,
        telemetry,
        camera,
        max_speed: limits.0,
        max_angular: limits.1,
    };
    for _ in 0..READERS {
        let server = server.clone();
        let shared = shared.clone();
        let running = running.clone();
        thread::spawn(move || {
            while running.load(Ordering::SeqCst) {
                match server.recv_timeout(PERIOD) {
                    Ok(Some(request)) => handle_request(request, &shared),
                    Ok(None) => {}
                    Err(error) => {
                        eprintln!("HTTP server stopped: {error}");
                        running.store(false, Ordering::SeqCst);
                    }
                }
            }
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn topic_names_are_restricted() {
        assert!(valid_topic("/esp32/lux"));
        assert!(!valid_topic("esp32"));
        assert!(!valid_topic("/a b"));
        assert!(!valid_topic("/a;rm"));
    }
}
