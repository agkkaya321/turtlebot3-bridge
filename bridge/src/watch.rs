//! Watch any topic on demand (e.g. an ESP32 sensor),
//! using message types compiled into the bridge (IDL_PACKAGE_FILTER).
use crate::{config::MAX_WATCHES, state::Telemetry};
use futures::{FutureExt, Stream, StreamExt};
use serde_json::{json, Value};
use std::{collections::BTreeMap, time::Instant};

/// Larger messages are not returned (maps, images, etc.).
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
            return Ok(format!("{topic} is already being watched"));
        }
        if self.streams.len() >= MAX_WATCHES {
            return Err(format!("At most {MAX_WATCHES} topics can be watched"));
        }
        let graph = node
            .get_topic_names_and_types()
            .map_err(|error| format!("Unable to read the ROS graph: {error}"))?;
        let Some(kind) = graph.get(topic).and_then(|types| types.first()).cloned() else {
            return Err(format!("{topic} does not exist in the ROS graph"));
        };
        // sensor_data (best effort) also receives messages from reliable publishers.
        let mut qos = r2r::QosProfile::sensor_data();
        qos.depth = 1;
        let stream = node
            .subscribe_untyped(topic, &kind, qos)
            .map_err(|error| format!("Type {kind} is not supported by the bridge: {error}"))?;
        self.streams.insert(topic.into(), Box::new(stream));
        telemetry.watched.insert(topic.into(), (kind.clone(), None));
        Ok(format!("Watching {topic} ({kind})"))
    }

    pub fn remove(&mut self, topic: &str, telemetry: &mut Telemetry) -> Result<String, String> {
        telemetry.watched.remove(topic);
        // Dropping the receiver is enough: r2r removes the subscription on the next cycle.
        match self.streams.remove(topic) {
            Some(_) => Ok(format!("No longer watching {topic}")),
            None => Err(format!("{topic} was not being watched")),
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
