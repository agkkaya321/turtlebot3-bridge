//! Observation à la demande de n'importe quel topic (ex. capteur ESP32),
//! pour les types de messages compilés dans le bridge (IDL_PACKAGE_FILTER).
use crate::{config::MAX_WATCHES, state::Telemetry};
use futures::{FutureExt, Stream, StreamExt};
use serde_json::{json, Value};
use std::{collections::BTreeMap, time::Instant};

/// Au-delà, le message n'est pas renvoyé (carte, image…).
const MAX_JSON: usize = 32 * 1024;

type Messages = Box<dyn Stream<Item = r2r::Result<Value>> + Unpin>;

#[derive(Default)]
pub struct Watches {
    streams: BTreeMap<String, Messages>,
}

impl Watches {
    pub fn add(
        &mut self,
        node: &mut r2r::Node,
        topic: &str,
        telemetry: &mut Telemetry,
    ) -> Result<String, String> {
        if self.streams.contains_key(topic) {
            return Ok(format!("{topic} déjà observé"));
        }
        if self.streams.len() >= MAX_WATCHES {
            return Err(format!("{MAX_WATCHES} topics observés au maximum"));
        }
        let graph = node
            .get_topic_names_and_types()
            .map_err(|error| format!("Graphe ROS illisible : {error}"))?;
        let Some(kind) = graph.get(topic).and_then(|types| types.first()).cloned() else {
            return Err(format!("{topic} n'existe pas dans le graphe ROS"));
        };
        if kind == "sensor_msgs/msg/Image" || kind == "sensor_msgs/msg/CompressedImage" {
            // Des centaines de milliers de valeurs JSON par image ralentiraient la boucle ROS.
            return Err(format!("{topic} est une image : utiliser la carte Caméra (GET /camera/frame)"));
        }
        // sensor_data (best effort) reçoit aussi les publishers fiables.
        let mut qos = r2r::QosProfile::sensor_data();
        qos.depth = 1;
        let stream = node
            .subscribe_untyped(topic, &kind, qos)
            .map_err(|error| format!("Type {kind} non pris en charge par le bridge : {error}"))?;
        self.streams.insert(topic.into(), Box::new(stream));
        telemetry.watched.insert(topic.into(), (kind.clone(), None));
        Ok(format!("{topic} ({kind}) observé"))
    }

    pub fn remove(&mut self, topic: &str, telemetry: &mut Telemetry) -> Result<String, String> {
        telemetry.watched.remove(topic);
        // Supprimer le récepteur suffit : r2r retire l'abonnement au cycle suivant.
        match self.streams.remove(topic) {
            Some(_) => Ok(format!("{topic} n'est plus observé")),
            None => Err(format!("{topic} n'était pas observé")),
        }
    }

    pub fn tick(&mut self, telemetry: &mut Telemetry) {
        for (topic, stream) in &mut self.streams {
            let mut last = None;
            for _ in 0..32 {
                match stream.next().now_or_never() {
                    Some(Some(message)) => last = Some(message),
                    _ => break,
                }
            }
            let Some(message) = last else { continue };
            let value = match message {
                Ok(value) if value.to_string().len() <= MAX_JSON => value,
                Ok(value) => json!({"tronqué": true, "octets": value.to_string().len()}),
                Err(error) => json!({"erreur": error.to_string()}),
            };
            if let Some(entry) = telemetry.watched.get_mut(topic) {
                entry.1 = Some((Instant::now(), value));
            }
        }
    }
}
