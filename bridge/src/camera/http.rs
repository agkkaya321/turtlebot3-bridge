//! Routes HTTP de la caméra.
//!
//! `GET /camera/frame?after=N` renvoie la première image plus récente que N
//! (attente de 2,5 s au plus, sinon 204). Le client ne demande l'image
//! suivante qu'après avoir reçu la précédente : le débit s'adapte seul au
//! Wi-Fi et aucune file d'images ne s'accumule dans le tunnel SSH.
//! L'attente se fait dans un thread dédié : les lecteurs HTTP de la conduite
//! ne sont jamais occupés par la vidéo.
use super::hub::{Frame, Hub, SettingsPatch};
use crate::http::{body, respond};
use serde_json::json;
use std::{
    sync::{atomic::Ordering, Arc},
    thread,
    time::Duration,
};
use tiny_http::{Header, Method, Request, Response};

/// Attente maximale d'une nouvelle image (sous le délai de 5 s de ui/server.py).
const WAIT: Duration = Duration::from_millis(2500);
/// Requêtes vidéo en attente simultanément.
const MAX_WAITING: usize = 4;

pub const ROUTES: &str = "GET /camera/frame?after=N /camera/status ; POST /camera/settings";

fn header(name: &str, value: impl ToString) -> Header {
    Header::from_bytes(name, value.to_string()).unwrap()
}

fn send_frame(request: Request, frame: &Frame, hub: &Hub) {
    let response = Response::from_data(frame.jpeg.clone())
        .with_header(header("Content-Type", "image/jpeg"))
        .with_header(header("Cache-Control", "no-store"))
        .with_header(header("X-Frame-Seq", frame.seq))
        .with_header(header("X-Frame-Width", frame.width))
        .with_header(header("X-Frame-Height", frame.height))
        .with_header(header("X-Frame-Quality", frame.quality))
        .with_header(header("X-Frame-Encode-Ms", frame.encode_ms))
        .with_header(header("X-Frame-Age-Ms", frame.captured.elapsed().as_millis()));
    if request.respond(response).is_ok() {
        hub.served(frame.jpeg.len());
    }
}

fn no_frame(request: Request) {
    let response = Response::empty(204).with_header(header("Cache-Control", "no-store"));
    let _ = request.respond(response);
}

fn after(url: &str) -> u64 {
    url.split_once('?')
        .map(|(_, query)| query)
        .unwrap_or("")
        .split('&')
        .find_map(|pair| pair.strip_prefix("after="))
        .and_then(|value| value.parse().ok())
        .unwrap_or(0)
}

fn frame(request: Request, hub: &Arc<Hub>) {
    let after = after(request.url());
    hub.demand();
    if let Some(frame) = hub.latest(after) {
        send_frame(request, &frame, hub);
        return;
    }
    if hub.waiting.fetch_add(1, Ordering::SeqCst) >= MAX_WAITING {
        hub.waiting.fetch_sub(1, Ordering::SeqCst);
        respond(request, 503, json!({"error": "Trop de lecteurs vidéo simultanés"}));
        return;
    }
    let hub = hub.clone();
    let spawned = thread::Builder::new()
        .name("camera-wait".into())
        .spawn(move || {
            match hub.wait(after, WAIT) {
                Some(frame) => send_frame(request, &frame, &hub),
                None => no_frame(request),
            }
            hub.waiting.fetch_sub(1, Ordering::SeqCst);
        });
    if let Err(error) = spawned {
        // La requête a été déplacée dans la fermeture : elle est abandonnée.
        eprintln!("Thread caméra impossible : {error}");
    }
}

/// Traite une route /camera/*.
pub fn handle(mut request: Request, path: &str, hub: &Arc<Hub>) {
    let method = request.method().clone();
    match (&method, path) {
        (Method::Get, "/camera/frame") => frame(request, hub),
        (Method::Get, "/camera/status") => respond(request, 200, hub.status_json()),
        (Method::Post, "/camera/settings") => match body::<SettingsPatch>(&mut request) {
            Ok(patch) => match hub.update_settings(&patch) {
                Ok(settings) => respond(request, 200, json!({"ok": true, "settings": settings.json()})),
                Err(error) => respond(request, 400, json!({ "error": error })),
            },
            Err(error) => respond(
                request,
                400,
                json!({"error": format!("Attendu : {{\"width\", \"quality\", \"fps\", \"rotate\"}} ({error})")}),
            ),
        },
        _ => respond(request, 404, json!({ "error": ROUTES })),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn after_is_read_from_the_query() {
        assert_eq!(after("/camera/frame"), 0);
        assert_eq!(after("/camera/frame?after=42"), 42);
        assert_eq!(after("/camera/frame?x=1&after=7"), 7);
        assert_eq!(after("/camera/frame?after=abc"), 0);
    }
}
