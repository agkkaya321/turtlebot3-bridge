"""First trial: move forward slowly for one second, then stop."""

import argparse

from robot import BridgeClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--speed", type=float, default=0.03, help="Speed in m/s")
    parser.add_argument("--seconds", type=float, default=1.0)
    args = parser.parse_args()

    robot = BridgeClient(args.url)
    print(robot.status())
    robot.wait_until_ready(timeout=60)
    with robot:
        print(robot.forward(args.speed))
        robot.wait(args.seconds)
        print(robot.stop())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Client interrupted.")
