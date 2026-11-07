// Slide content and speaker notes. The 3D stage for each slide is selected in scene.js by index.
// Status vocabulary (brief §2): Existing / Planned / To define (or validate).
const OK = '<span class="pill ok">Existing</span>';
const PLAN = '<span class="pill plan">Planned</span>';
const TBD = '<span class="pill tbd">To define</span>';

export const SLIDES = [
  {
    kicker: 'Presentation 2 · How it works',
    title: 'NextStep: guiding a training session, one step at a time',
    tag: 'Illustration',
    html: `
      <p class="lead">A mobile robot observes a person during an exercise, then shows on the floor — with a laser spot — where to place the next foot.</p>
      <div class="slide-body">
        <p>Today: how the system is meant to go from <strong>observing the person</strong> to a <strong>step target on the floor</strong>, and what is still to build.</p>
        <p class="authors">Ali Gökkaya and Jason Condrea</p>
      </div>`,
    notes: `
      <p>Our first presentation introduced the idea: a robot that watches the posture, uses vital parameters, and points with a laser where the next foot should go.</p>
      <p>Today we go one level deeper: how the pieces connect. At the end you should know what the person does, what the robot does, which data feed the decisions, how one cycle runs, and what is still missing.</p>
      <p>Important: the animations illustrate the intended behaviour. They are not a recording of the real robot.</p>`,
  },
  {
    kicker: 'The idea',
    title: 'The user’s experience',
    tag: 'Illustration',
    html: `
      <p class="lead">A session is one short cycle, repeated until the end of the training.</p>
      <div class="slide-body">
        <ol class="live" data-live="phase4">
          <li><strong>The robot backs up</strong> to make room for the next step.</li>
          <li><strong>It observes the posture</strong> of the person with its camera.</li>
          <li><strong>It marks a target</strong> on the floor with the laser.</li>
          <li><strong>The person steps</strong> onto the target — then the cycle starts again.</li>
        </ol>
        <p>Targets alternate: <strong>left foot, then right foot</strong>.</p>
      </div>`,
    notes: `
      <p>From the user’s point of view it is simple: the robot moves back, looks at you, a spot appears on the floor, you put your foot there.</p>
      <p>The highlighted line on the left follows the animation. The robot always faces the person while it backs up, because the camera has to keep the person in view.</p>
      <p>The targets alternate between the left and the right foot, exactly as in our first presentation. When the session ends is still to be defined.</p>`,
  },
  {
    kicker: 'Hardware',
    title: 'The components and their roles',
    tag: 'Illustration · placement of parts not final',
    html: `
      <p class="lead">Each component answers one question: how to move, how to see, how to measure, how to show.</p>
      <div class="slide-body">
        <ul>
          <li><strong>TurtleBot3 Burger</strong> — mobile base with Raspberry Pi, OpenCR board and LiDAR. Moves and reads its sensors. ${OK}</li>
          <li><strong>Logitech BRIO 105</strong> — webcam that films the person. Chosen, to integrate. ${PLAN}</li>
          <li><strong>Wearable sensors</strong> — heart rate (BPM) and oxygen saturation (SpO₂). Models to choose. ${PLAN}</li>
          <li><strong>Laser + two-gear mount</strong> — marks the target on the floor. ${PLAN}</li>
        </ul>
      </div>`,
    notes: `
      <p>The base is a standard TurtleBot3 Burger: a Raspberry Pi runs Ubuntu and ROS 2, the OpenCR board drives the motors, and a LiDAR scans around the robot. The exact LiDAR model is still to be confirmed in the documentation.</p>
      <p>We chose the Logitech BRIO 105 webcam; it replaces the C270 mentioned in older documents. It is not integrated yet.</p>
      <p>The wearable sensors and the laser mount are planned. The position of the camera and of the mount on the robot in the 3D view is only illustrative.</p>`,
  },
  {
    kicker: 'Observation · 1/2',
    title: 'From the image to body landmarks',
    tag: 'Illustration',
    html: `
      <p class="lead">The camera only gives pixels. Vision turns them into a few points placed on the body.</p>
      <div class="slide-body">
        <ol class="live chain" data-live="vision">
          <li><strong>Capture</strong> — the BRIO 105 films the person.</li>
          <li><strong>OpenCV</strong> — reads and prepares the images.</li>
          <li><strong>MediaPipe</strong> — finds body keypoints: shoulders, elbows, hips, knees…</li>
          <li><strong>Markers</strong> — digital points drawn on the image. <small>Not the laser spot on the floor.</small></li>
        </ol>
        <p class="fine">Whole chain ${PLAN} · runs on the Pi or the Mac ${TBD}</p>
      </div>`,
    notes: `
      <p>Step one is acquisition: images from the BRIO 105. OpenCV is the image toolbox — reading frames, converting and preparing them.</p>
      <p>MediaPipe is the part that recognises the body: it returns keypoints such as shoulders, hips and knees. We call them markers: they are digital points on the image. They have nothing to do with the laser spot, which is a physical light on the floor.</p>
      <p>Where this runs — on the Raspberry Pi or on the Mac — is not decided. The camera stream is not in the bridge yet, and the generic topic observation (32 KiB per JSON message) is not a video transport.</p>`,
  },
  {
    kicker: 'Observation · 2/2',
    title: 'From landmarks to posture quality',
    tag: 'Illustration · no measured values',
    html: `
      <p class="lead">Idea: measure the angles between an axis standing for the spine and the limbs.</p>
      <div class="slide-body">
        <ul>
          <li><strong>Trunk axis</strong> — built from landmarks (e.g. hips → shoulders). An approximation, not the real spine. ${TBD}</li>
          <li><strong>Angles θ</strong> — between that axis and the arms and legs.</li>
          <li><strong>Goal from presentation 1</strong> — judge stability and lordosis (lumbar curvature).</li>
          <li><strong>Limit</strong> — an angle estimate is not a clinical measurement of lordosis. Landmarks, angles and thresholds are still ${TBD}</li>
        </ul>
      </div>`,
    notes: `
      <p>Once we have landmarks, we can draw a reference line for the trunk, for example from the middle of the hips to the middle of the shoulders, and compute angles with the limbs.</p>
      <p>The θ symbols are placeholders: we do not show values because no score formula or threshold exists yet.</p>
      <p>Our first presentation talked about stability and lordosis. This angle method is a way to approach those goals, but it is an estimate from a camera, not a clinical measurement. Which points, which angles and which thresholds remain open questions.</p>`,
  },
  {
    kicker: 'Decision',
    title: 'Adapting the current difficulty',
    tag: 'Simulation · illustrative values',
    html: `
      <p class="lead">Keep the exercise accessible, yet demanding enough to be useful.</p>
      <div class="slide-body">
        <ul>
          <li><strong>Input 1 — posture</strong> from the vision chain.</li>
          <li><strong>Input 2 — vital parameters</strong> from wearable sensors: heart rate (BPM) and SpO₂ (%). ${PLAN}</li>
          <li><strong>Adaptation rule</strong> — how the inputs set the current difficulty. No formula yet. ${TBD}</li>
          <li><strong>Output</strong> — the target of the next step.</li>
        </ul>
        <p class="fine">The readings on the right are simulated. We do not infer fatigue or any diagnosis from them.</p>
      </div>`,
    notes: `
      <p>The current difficulty is the level of the exercise right now. The aim is a balance: not so hard that the person struggles, not so easy that it is useless.</p>
      <p>Two sources of information are planned: the posture estimate and the vital parameters — heart rate and oxygen saturation, as in the first presentation. The values shown are simulated.</p>
      <p>The rule that combines them is not designed yet. In the animation the target moves nearer or farther only to show that the output is a target position; this is an illustration, not a defined behaviour.</p>`,
  },
  {
    kicker: 'Control',
    title: 'Orchestrating the cycle with a state machine',
    tag: 'Target behaviour · illustration',
    html: `
      <p class="lead"><strong>State</strong> = what the robot is doing now. <strong>Transition</strong> = the condition that lets it move on.</p>
      <div class="slide-body">
        <ol class="live" data-live="fsm">
          <li><strong>Back up</strong></li>
          <li><strong>Estimate posture</strong></li>
          <li><strong>Aim the laser</strong> — left, then right foot</li>
          <li><strong>Wait for the step</strong> ${PLAN}</li>
        </ol>
        <p>Repeat until the <strong>end of the session</strong> ${PLAN}. Every transition condition is ${TBD}</p>
        <p class="fine">In code: a first structure in <code>fsm.py</code> declares <code>initial</code>, <code>posture_checking</code>, <code>moving_backward</code>, <code>laser_aiming_left/right</code>. Actions only print to the console; transitions are still to finish.</p>
      </div>`,
    notes: `
      <p>A state machine is a simple way to organise behaviour: the robot is always in exactly one state, and a transition fires when its condition is met.</p>
      <p>The order we want is: back up, estimate the posture, aim the laser — alternating left and right foot — wait for the step, and repeat. “Wait for the step” and “end of session” are part of the target design, not implemented.</p>
      <p>We still have to define how to recognise the end of the back-up, a usable posture estimate, a confirmed laser placement, a completed step and the end of the session. The order of the states in the code file does not define this order. main.py does not use the state machine yet.</p>`,
  },
  {
    kicker: 'Action',
    title: 'Turning a target into a laser spot',
    tag: 'Concept — mechanics to be defined',
    html: `
      <p class="lead">Choosing <em>where</em> the foot should go is not the same as physically pointing the laser there.</p>
      <div class="slide-body">
        <ol class="chain">
          <li><strong>Target</strong> — a point on the floor, chosen by the software. ${TBD}</li>
          <li><strong>Command</strong> — converts that point into an aiming angle for the mount. ${TBD}</li>
          <li><strong>Mechanism</strong> — two gears change the aiming angle of the laser. ${PLAN}</li>
        </ol>
        <p class="fine">Assembly, actuators, control interface and pointing accuracy are still to be defined. The 3D model is a design draft.</p>
      </div>`,
    notes: `
      <p>We separate three layers. The software decides a target point on the floor. A command layer has to translate that point into an orientation for the laser. And the mechanism physically moves the laser.</p>
      <p>The mechanism we are designing uses two gears to change the aiming angle of the laser; you see our draft model on the robot.</p>
      <p>How it is mounted, what drives it, how it is commanded and how precise it is are not decided yet. The number of gears alone does not tell how many independent movements the mechanism has.</p>`,
  },
  {
    kicker: 'Software architecture',
    title: 'How the Mac talks to the robot',
    tag: 'Existing path · planned vision · illustration',
    html: `
      <p class="lead">Follow one command from the Mac to the motors.</p>
      <div class="slide-body">
        <ol class="chain">
          <li><strong>Python client</strong> (<code>Robot</code>, <code>BridgeClient</code>) programs the behaviour on the Mac. ${OK}</li>
          <li><strong>HTTP through an SSH tunnel</strong> carries it to the robot. ${OK}</li>
          <li><strong>Rust bridge</strong> on the Raspberry Pi exposes ROS commands, sensors and services as an HTTP API. ${OK}</li>
          <li><strong>ROS 2 Jazzy</strong> (Ubuntu 24.04) talks to the motors and sensors.</li>
        </ol>
        <p class="fine">Docker only builds the ARM64 bridge on the Mac. No ROS needed on the Mac. A local web UI shows control and telemetry. Vision: ${PLAN} — where it runs and how images travel ${TBD}</p>
      </div>`,
    notes: `
      <p>This part exists. On the Mac, a Python client written with the standard library sends HTTP requests. They go through an SSH tunnel to the robot.</p>
      <p>On the Raspberry Pi, a bridge written in Rust receives them and talks to ROS 2, which drives the motors and reads the LiDAR and other sensors. ROS stays on the robot; the Mac does not need it.</p>
      <p>Docker is only a build tool: it compiles the bridge for the ARM64 Raspberry Pi on the Mac. The vision module is planned, and we have not decided whether it runs on the Pi or on the Mac, nor how images are transported.</p>`,
  },
  {
    kicker: 'Putting it together',
    title: 'One complete cycle, step by step',
    tag: 'Illustrative scenario',
    html: `
      <p class="lead">For each stage: what happens, and what must be true to continue.</p>
      <div class="slide-body">
        <ol class="live steps" data-live="phase5">
          <li><strong>Back up</strong> — the robot moves away. <span class="when">Continue when the back-up is finished ${TBD}</span></li>
          <li><strong>Estimate</strong> — a usable image gives a posture estimate. <span class="when">Continue when the estimate is usable ${TBD}</span></li>
          <li><strong>Choose target</strong> — posture + vitals → next target. <span class="when">Rule to design ${TBD}</span></li>
          <li><strong>Mark</strong> — the laser shows the target. <span class="when">Continue when the placement is confirmed ${TBD}</span></li>
          <li><strong>Step</strong> — the person steps on it. <span class="when">Step detection, then back to 1 ${TBD}</span></li>
        </ol>
      </div>`,
    notes: `
      <p>Let us follow one step. The robot finishes backing up. It gets an image good enough to estimate the posture. From the posture and the vital parameters the system will have to deduce a target. The laser marks it. The person steps. A detection condition, still to define, allows the next cycle.</p>
      <p>The timeline on the right shows the same thing in three lanes: what the robot does, what the processing does, and what the person does.</p>
      <p>This is how we want it to work — not a demonstration that already runs.</p>`,
  },
  {
    kicker: 'Status',
    title: 'What exists and what remains to build',
    tag: 'Project status',
    html: `
      <div class="slide-body cols">
        <div class="c1"><h3><span class="pill ok">Existing</span></h3><ul>
          <li>Rust bridge: HTTP API ↔ ROS 2</li>
          <li>Python client <code>Robot</code> / <code>BridgeClient</code></li>
          <li>Local web UI: control + telemetry</li>
          <li>Tested in a container and against a fake robot</li>
        </ul></div>
        <div class="c2"><h3><span class="pill plan">Planned</span></h3><ul>
          <li>State machine — first structure in <code>fsm.py</code></li>
          <li>Vision: BRIO 105 + OpenCV + MediaPipe</li>
          <li>Laser + two-gear mount</li>
          <li>Wearable sensors (BPM, SpO₂)</li>
        </ul></div>
        <div class="c3"><h3><span class="pill tbd">To define / validate</span></h3><ul>
          <li>Landmarks, trunk axis, angles, thresholds</li>
          <li>Difficulty rule</li>
          <li>Step detection, end of session</li>
          <li>Laser mechanics and control</li>
          <li>Image transport, where vision runs</li>
          <li>Full cycle on the real robot</li>
        </ul></div>
      </div>`,
    notes: `
      <p>The communication layer exists: bridge, client and web interface. The documentation reports tests in a container and against a fake robot — that is software validation, not a validation of the full system on the real robot.</p>
      <p>The state machine has a first structure. Vision, the laser mount and the wearable sensors are planned components.</p>
      <p>And the right column lists the decisions that are still open; they are the core of our next work.</p>`,
  },
  {
    kicker: 'Next steps',
    title: 'Thank you — questions?',
    tag: 'Illustration',
    html: `
      <p class="lead">Next: integrate the cycle back up → estimate → laser → step, then verify it on the robot.</p>
      <div class="slide-body">
        <ul>
          <li>Connect the state machine to the bridge and define its transitions.</li>
          <li>Choose landmarks and angles, then the difficulty rule.</li>
          <li>Build the laser mount and its command.</li>
          <li>Decide where vision runs and how images travel.</li>
          <li>Detect the step and the end of the session.</li>
        </ul>
        <p class="authors">Ali Gökkaya and Jason Condrea</p>
      </div>`,
    notes: `
      <p>To sum up: the communication with the robot exists; the training cycle is designed and has to be integrated and verified.</p>
      <p>Our next decisions are the angle computation, the difficulty rule, step detection, the laser mechanics, the image transport and the end-of-session criteria.</p>
      <p>Thank you for listening — we are happy to take your questions.</p>`,
  },
];
