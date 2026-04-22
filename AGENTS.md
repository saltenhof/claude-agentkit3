# Local Agent Instructions

- Keep Jenkins green before closing substantial work: `http://localhost:9900/job/claude-agentkit3/`
- Keep Sonar green before closing substantial work: `http://192.168.0.20:9901`
- Sonar target is strict: `violations=0`, `critical_violations=0`, `open_hotspots=0`
- Local Sonar credentials for this workspace: `admin` / `meinSonarCube2026!`
- Treat concept updates and code changes the same way: do not leave the repo in a state that breaks Jenkins or the Sonar quality gate
