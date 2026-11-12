# NextStep — Presentation 2 · Speaker notes

Ali Gökkaya and Jason Condrea · 12 slides · open with `start.command` (http://localhost:8770). Keys: ←/→ slides, **N** notes, **F** full screen, **Space** pause, **R** restart.

---

## 1. NextStep: guiding a training session, one step at a time

*Visual tag: Illustration*

### On the slide

A mobile robot observes a person during an exercise, then shows on the floor — with a laser spot — where to place the next foot.

Today: how the system is meant to go from **observing the person** to a **step target on the floor**, and what is still to build.

Ali Gökkaya and Jason Condrea

### Say

Our first presentation introduced the idea: a robot that watches the posture, uses vital parameters, and points with a laser where the next foot should go.

Today we go one level deeper: how the pieces connect. At the end you should know what the person does, what the robot does, which data feed the decisions, how one cycle runs, and what is still missing.

Important: the animations illustrate the intended behaviour. They are not a recording of the real robot.

---

## 2. The user’s experience

*Visual tag: Illustration*

### On the slide

A session is one short cycle, repeated until the end of the training.

- **The robot backs up** to make room for the next step.

- **It observes the posture** of the person with its camera.

- **It marks a target** on the floor with the laser.

- **The person steps** onto the target — then the cycle starts again.

Targets alternate: **left foot, then right foot**.

### Say

From the user’s point of view it is simple: the robot moves back, looks at you, a spot appears on the floor, you put your foot there.

The highlighted line on the left follows the animation. The robot always faces the person while it backs up, because the camera has to keep the person in view.

The targets alternate between the left and the right foot, exactly as in our first presentation. When the session ends is still to be defined.

---

## 3. The components and their roles

*Visual tag: Illustration · placement of parts not final*

### On the slide

Each component answers one question: how to move, how to see, how to measure, how to show.

- **TurtleBot3 Burger** — mobile base with Raspberry Pi, OpenCR board and LiDAR. Moves and reads its sensors. [Existing]

- **Logitech BRIO 105** — webcam that films the person. Chosen, to integrate. [Planned]

- **Wearable sensors** — heart rate (BPM) and oxygen saturation (SpO₂). Models to choose. [Planned]

- **Laser + two-gear mount** — marks the target on the floor. [Planned]

### Say

The base is a standard TurtleBot3 Burger: a Raspberry Pi runs Ubuntu and ROS 2, the OpenCR board drives the motors, and a LiDAR scans around the robot. The exact LiDAR model is still to be confirmed in the documentation.

We chose the Logitech BRIO 105 webcam; it replaces the C270 mentioned in older documents. It is not integrated yet.

The wearable sensors and the laser mount are planned. The position of the camera and of the mount on the robot in the 3D view is only illustrative.

---

## 4. From the image to body landmarks

*Visual tag: Illustration*

### On the slide

The camera only gives pixels. Vision turns them into a few points placed on the body.

- **Capture** — the BRIO 105 films the person.

- **OpenCV** — reads and prepares the images.

- **MediaPipe** — finds body keypoints: shoulders, elbows, hips, knees…

- **Markers** — digital points drawn on the image. Not the laser spot on the floor.

Whole chain [Planned] · runs on the Pi or the Mac [To define]

### Say

Step one is acquisition: images from the BRIO 105. OpenCV is the image toolbox — reading frames, converting and preparing them.

MediaPipe is the part that recognises the body: it returns keypoints such as shoulders, hips and knees. We call them markers: they are digital points on the image. They have nothing to do with the laser spot, which is a physical light on the floor.

Where this runs — on the Raspberry Pi or on the Mac — is not decided. The camera stream is not in the bridge yet, and the generic topic observation (32 KiB per JSON message) is not a video transport.

---

## 5. From landmarks to posture quality

*Visual tag: Illustration · no measured values*

### On the slide

Idea: measure the angles between an axis standing for the spine and the limbs.

- **Trunk axis** — built from landmarks (e.g. hips → shoulders). An approximation, not the real spine. [To define]

- **Angles θ** — between that axis and the arms and legs.

- **Goal from presentation 1** — judge stability and lordosis (lumbar curvature).

- **Limit** — an angle estimate is not a clinical measurement of lordosis. Landmarks, angles and thresholds are still [To define]

### Say

Once we have landmarks, we can draw a reference line for the trunk, for example from the middle of the hips to the middle of the shoulders, and compute angles with the limbs.

The θ symbols are placeholders: we do not show values because no score formula or threshold exists yet.

Our first presentation talked about stability and lordosis. This angle method is a way to approach those goals, but it is an estimate from a camera, not a clinical measurement. Which points, which angles and which thresholds remain open questions.

---

## 6. Adapting the current difficulty

*Visual tag: Simulation · illustrative values*

### On the slide

Keep the exercise accessible, yet demanding enough to be useful.

- **Input 1 — posture** from the vision chain.

- **Input 2 — vital parameters** from wearable sensors: heart rate (BPM) and SpO₂ (%). [Planned]

- **Adaptation rule** — how the inputs set the current difficulty. No formula yet. [To define]

- **Output** — the target of the next step.

The readings on the right are simulated. We do not infer fatigue or any diagnosis from them.

### Say

The current difficulty is the level of the exercise right now. The aim is a balance: not so hard that the person struggles, not so easy that it is useless.

Two sources of information are planned: the posture estimate and the vital parameters — heart rate and oxygen saturation, as in the first presentation. The values shown are simulated.

The rule that combines them is not designed yet. In the animation the target moves nearer or farther only to show that the output is a target position; this is an illustration, not a defined behaviour.

---

## 7. Orchestrating the cycle with a state machine

*Visual tag: Target behaviour · illustration*

### On the slide

**State** = what the robot is doing now. **Transition** = the condition that lets it move on.

- **Back up**

- **Estimate posture**

- **Aim the laser** — left, then right foot

- **Wait for the step** [Planned]

Repeat until the **end of the session** [Planned]. Every transition condition is [To define]

In code: a first structure in `fsm.py` declares `initial`, `posture_checking`, `moving_backward`, `laser_aiming_left/right`. Actions only print to the console; transitions are still to finish.

### Say

A state machine is a simple way to organise behaviour: the robot is always in exactly one state, and a transition fires when its condition is met.

The order we want is: back up, estimate the posture, aim the laser — alternating left and right foot — wait for the step, and repeat. “Wait for the step” and “end of session” are part of the target design, not implemented.

We still have to define how to recognise the end of the back-up, a usable posture estimate, a confirmed laser placement, a completed step and the end of the session. The order of the states in the code file does not define this order. main.py does not use the state machine yet.

---

## 8. Turning a target into a laser spot

*Visual tag: Concept — mechanics to be defined*

### On the slide

Choosing where the foot should go is not the same as physically pointing the laser there.

- **Target** — a point on the floor, chosen by the software. [To define]

- **Command** — converts that point into an aiming angle for the mount. [To define]

- **Mechanism** — two gears change the aiming angle of the laser. [Planned]

Assembly, actuators, control interface and pointing accuracy are still to be defined. The 3D model is a design draft.

### Say

We separate three layers. The software decides a target point on the floor. A command layer has to translate that point into an orientation for the laser. And the mechanism physically moves the laser.

The mechanism we are designing uses two gears to change the aiming angle of the laser; you see our draft model on the robot.

How it is mounted, what drives it, how it is commanded and how precise it is are not decided yet. The number of gears alone does not tell how many independent movements the mechanism has.

---

## 9. How the Mac talks to the robot

*Visual tag: Existing path · planned vision*

### On the slide

Follow one command from the Mac to the motors.

- **Python client** (`Robot`, `BridgeClient`) programs the behaviour on the Mac. [Existing]

- **HTTP through an SSH tunnel** carries it to the robot. [Existing]

- **Rust bridge** on the Raspberry Pi exposes ROS commands, sensors and services as an HTTP API. [Existing]

- **ROS 2 Jazzy** (Ubuntu 24.04) talks to the motors and sensors.

Docker only builds the ARM64 bridge on the Mac. No ROS needed on the Mac. A local web UI shows control and telemetry. Vision: [Planned] — where it runs and how images travel [To define]

### Say

This part exists. On the Mac, a Python client written with the standard library sends HTTP requests. They go through an SSH tunnel to the robot.

On the Raspberry Pi, a bridge written in Rust receives them and talks to ROS 2, which drives the motors and reads the LiDAR and other sensors. ROS stays on the robot; the Mac does not need it.

Docker is only a build tool: it compiles the bridge for the ARM64 Raspberry Pi on the Mac. The vision module is planned, and we have not decided whether it runs on the Pi or on the Mac, nor how images are transported.

---

## 10. One complete cycle, step by step

*Visual tag: Illustrative scenario*

### On the slide

For each stage: what happens, and what must be true to continue.

- **Back up** — the robot moves away. Continue when the back-up is finished [To define]

- **Estimate** — a usable image gives a posture estimate. Continue when the estimate is usable [To define]

- **Choose target** — posture + vitals → next target. Rule to design [To define]

- **Mark** — the laser shows the target. Continue when the placement is confirmed [To define]

- **Step** — the person steps on it. Step detection, then back to 1 [To define]

### Say

Let us follow one step. The robot finishes backing up. It gets an image good enough to estimate the posture. From the posture and the vital parameters the system will have to deduce a target. The laser marks it. The person steps. A detection condition, still to define, allows the next cycle.

The timeline on the right shows the same thing in three lanes: what the robot does, what the processing does, and what the person does.

This is how we want it to work — not a demonstration that already runs.

---

## 11. What exists and what remains to build

*Visual tag: Project status*

### On the slide

[Existing]

- Rust bridge: HTTP API ↔ ROS 2

- Python client `Robot` / `BridgeClient`

- Local web UI: control + telemetry

- Tested in a container and against a fake robot

[Planned]

- State machine — first structure in `fsm.py`

- Vision: BRIO 105 + OpenCV + MediaPipe

- Laser + two-gear mount

- Wearable sensors (BPM, SpO₂)

To define / validate

- Landmarks, trunk axis, angles, thresholds

- Difficulty rule

- Step detection, end of session

- Laser mechanics and control

- Image transport, where vision runs

- Full cycle on the real robot

### Say

The communication layer exists: bridge, client and web interface. The documentation reports tests in a container and against a fake robot — that is software validation, not a validation of the full system on the real robot.

The state machine has a first structure. Vision, the laser mount and the wearable sensors are planned components.

And the right column lists the decisions that are still open; they are the core of our next work.

---

## 12. Thank you — questions?

*Visual tag: Illustration*

### On the slide

Next: integrate the cycle back up → estimate → laser → step, then verify it on the robot.

- Connect the state machine to the bridge and define its transitions.

- Choose landmarks and angles, then the difficulty rule.

- Build the laser mount and its command.

- Decide where vision runs and how images travel.

- Detect the step and the end of the session.

Ali Gökkaya and Jason Condrea

### Say

To sum up: the communication with the robot exists; the training cycle is designed and has to be integrated and verified.

Our next decisions are the angle computation, the difficulty rule, step detection, the laser mechanics, the image transport and the end-of-session criteria.

Thank you for listening — we are happy to take your questions.
