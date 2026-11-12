//! Boucle ROS : capteurs, état, consignes, services et expiration des commandes.
use crate::{
    camera::Camera,
    config::{Config, LEASE, PERIOD},
    health::Health,
    sensors,
    services::Services,
    state::{self, Command, Request, SharedStatus, SharedTelemetry, Status},
    supervisor::Supervisor,
    velocity::{Velocity, VelocityPublisher},
    watch::Watches,
    BridgeResult,
};
use futures::{FutureExt, Stream, StreamExt};
use r2r::{
    nav_msgs::msg::Odometry,
    sensor_msgs::msg::{BatteryState, Imu, JointState, LaserScan, MagneticField},
    turtlebot3_msgs::msg::SensorState,
};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{Receiver, SyncSender},
    },
    thread,
    time::{Duration, Instant},
};

/// Commandes traitées par cycle : l'interface renvoie la vitesse à 10 Hz
/// pendant qu'un appel de service peut aussi arriver.
const COMMANDS_PER_CYCLE: usize = 8;
/// Rafraîchissement de la liste des topics, en cycles (1 s).
const GRAPH_EVERY: u32 = 20;

/// Dernier message disponible, en bornant le travail par cycle.
pub(crate) fn latest<T>(stream: &mut (impl Stream<Item = T> + Unpin)) -> Option<T> {
    let mut last = None;
    for _ in 0..32 {
        match stream.next().now_or_never() {
            Some(Some(message)) => last = Some(message),
            _ => break,
        }
    }
    last
}

pub fn run(
    config: &Config,
    commands: &Receiver<Command>,
    status: &SharedStatus,
    telemetry: &SharedTelemetry,
    running: &AtomicBool,
    supervisor: &mut Supervisor,
    camera: &mut Camera,
) -> BridgeResult<()> {
    let context = r2r::Context::create()?;
    let mut node = r2r::Node::create(context, "turtlebot_speed_bridge", "")?;
    let mut qos = r2r::QosProfile::default();
    qos.depth = 1;
    let publisher = if config.stamped {
        VelocityPublisher::Stamped(node.create_publisher(&config.velocity_topic, qos)?)
    } else {
        VelocityPublisher::Plain(node.create_publisher(&config.velocity_topic, qos)?)
    };
    let mut sensors_qos = r2r::QosProfile::sensor_data();
    sensors_qos.depth = 1;
    let mut odometry = node.subscribe::<Odometry>(&config.odometry_topic, sensors_qos.clone())?;
    let mut sensor_state =
        node.subscribe::<SensorState>(&config.sensor_topic, sensors_qos.clone())?;
    let mut battery = node.subscribe::<BatteryState>(&config.battery_topic, sensors_qos.clone())?;
    let mut imu = node.subscribe::<Imu>(&config.imu_topic, sensors_qos.clone())?;
    let mut scan = node.subscribe::<LaserScan>(&config.scan_topic, sensors_qos.clone())?;
    let mut magnetic =
        node.subscribe::<MagneticField>(&config.magnetic_topic, sensors_qos.clone())?;
    let mut joints = node.subscribe::<JointState>(&config.joint_topic, sensors_qos)?;
    let mut services = Services::new(&mut node, config)?;
    let mut watches = Watches::default();
    // Nouveau nœud : l'ancien abonnement caméra n'est plus valable.
    camera.detach();
    state::lock(telemetry).watched.clear();
    let mut clock = r2r::Clock::create(r2r::ClockType::SystemTime)?;
    let mut health = Health::default();
    let mut velocity = Velocity::ZERO;
    let mut last_command = Instant::now();
    // Toute perte de readiness invalide aussi les requêtes arrivées avant sa récupération.
    let mut commands_after = Instant::now();
    let mut cycles: u32 = 0;

    let result = (|| -> BridgeResult<()> {
        while running.load(Ordering::SeqCst) {
            let cycle = Instant::now();
            node.spin_once(Duration::ZERO);
            let odom_message = latest(&mut odometry);
            let sensor_message = latest(&mut sensor_state);
            if let Some(message) = &odom_message {
                health.odometry(message);
            }
            if let Some(message) = &sensor_message {
                health.sensors(message);
            }
            {
                let mut shared = state::lock(telemetry);
                if let Some(message) = &odom_message {
                    shared.set("odom", sensors::odometry(message));
                }
                if let Some(message) = &sensor_message {
                    shared.set("sensor_state", sensors::sensor_state(message));
                }
                if let Some(message) = latest(&mut battery) {
                    shared.set("battery", sensors::battery(&message));
                }
                if let Some(message) = latest(&mut imu) {
                    shared.set("imu", sensors::imu(&message));
                }
                if let Some(message) = latest(&mut scan) {
                    shared.set("scan", sensors::scan(&message));
                }
                if let Some(message) = latest(&mut magnetic) {
                    shared.set("magnetic_field", sensors::magnetic_field(&message));
                }
                if let Some(message) = latest(&mut joints) {
                    shared.set("joint_states", sensors::joint_states(&message));
                }
                watches.tick(&mut shared);
            }
            // Caméra : dépôt de la dernière image et pilote usb_cam, sans erreur possible ici.
            camera.tick(&mut node, cycles);
            services.tick()?;

            let subscribers = publisher.subscriber_count()?;
            let external = !node
                .get_publishers_info_by_topic(&config.sensor_topic, false)?
                .is_empty()
                || !node
                    .get_publishers_info_by_topic(&config.odometry_topic, false)?
                    .is_empty()
                || subscribers > 0;
            supervisor.tick(config, health.ros_alive(), external, || {
                if let Err(error) = publisher.publish(Velocity::ZERO, &mut clock) {
                    eprintln!("Arrêt avant relance non confirmé : {error}");
                }
            });
            let reason = if !supervisor.allows_motion() {
                Some("Redémarrage du bringup en cours")
            } else {
                health.reason(subscribers)
            };
            let ready = reason.is_none();
            if !ready {
                velocity = Velocity::ZERO;
                commands_after = Instant::now();
            }

            let mut acknowledgements: Vec<SyncSender<Result<String, String>>> = Vec::new();
            for _ in 0..COMMANDS_PER_CYCLE {
                let Ok(command) = commands.try_recv() else {
                    break;
                };
                let Command {
                    request,
                    received_at,
                    reply,
                } = command;
                match request {
                    Request::Velocity(requested) => {
                        let error = if received_at.elapsed() >= LEASE {
                            Some("Commande expirée")
                        } else if !requested.is_zero() && (!ready || received_at < commands_after) {
                            Some("not ready : attendre ready puis envoyer une nouvelle commande")
                        } else {
                            None
                        };
                        if let Some(error) = error {
                            let _ = reply.send(Err(error.into()));
                        } else {
                            velocity = requested;
                            last_command = received_at;
                            acknowledgements.push(reply);
                        }
                    }
                    Request::MotorPower(enabled) => {
                        if !enabled {
                            // Demander l'arrêt avant de couper le couple.
                            velocity = Velocity::ZERO;
                            publisher.publish(velocity, &mut clock)?;
                        }
                        if let Err(error) = services.motor_power(enabled, reply.clone()) {
                            let _ = reply.send(Err(format!("Requête motor_power : {error}")));
                        }
                    }
                    Request::Sound(value) => {
                        if let Err(error) = services.sound(value, reply.clone()) {
                            let _ = reply.send(Err(format!("Requête sound : {error}")));
                        }
                    }
                    Request::Reset => {
                        // Le reset peut recalibrer l'IMU : jamais pendant un mouvement.
                        velocity = Velocity::ZERO;
                        publisher.publish(velocity, &mut clock)?;
                        if let Err(error) = services.reset(reply.clone()) {
                            let _ = reply.send(Err(format!("Requête reset : {error}")));
                        }
                    }
                    Request::Watch(topic) => {
                        let result = watches.add(&mut node, &topic, &mut state::lock(telemetry));
                        let _ = reply.send(result);
                    }
                    Request::Unwatch(topic) => {
                        let _ = reply.send(watches.remove(&topic, &mut state::lock(telemetry)));
                    }
                }
            }
            if last_command.elapsed() >= LEASE {
                velocity = Velocity::ZERO;
            }
            if let Err(error) = publisher.publish(velocity, &mut clock) {
                for reply in acknowledgements {
                    let _ = reply.send(Err(format!("Publication ROS impossible : {error}")));
                }
                return Err(error.into());
            }
            for reply in acknowledgements {
                let _ = reply.send(Ok("published".into()));
            }

            {
                let mut shared = state::lock(telemetry);
                shared.velocity = velocity;
                services.publish(&mut shared);
                if cycles % GRAPH_EVERY == 0 {
                    if let Ok(graph) = node.get_topic_names_and_types() {
                        let mut topics: Vec<_> = graph.into_iter().collect();
                        topics.sort();
                        shared.topics = topics;
                    }
                }
            }
            cycles = cycles.wrapping_add(1);
            state::update(
                status,
                Status {
                    ready,
                    reason: reason.unwrap_or("ok").into(),
                    ros_alive: health.ros_alive(),
                    supervisor: supervisor.description.clone(),
                    updated: Instant::now(),
                },
            );
            thread::sleep(PERIOD.saturating_sub(cycle.elapsed()));
        }
        Ok(())
    })();
    state::update(
        status,
        Status::waiting("Boucle ROS arrêtée ou en récupération"),
    );
    services.abort();
    camera.detach();
    state::lock(telemetry).velocity = Velocity::ZERO;
    for _ in 0..3 {
        if let Err(error) = publisher.publish(Velocity::ZERO, &mut clock) {
            eprintln!("Impossible de publier l'arrêt : {error}");
        }
        thread::sleep(PERIOD);
    }
    result
}
