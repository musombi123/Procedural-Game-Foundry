# NEXORA managed compute runtime

## What this provisions

The private NEXORA managed-compute container has a preinstalled Linux headless toolchain:

- Blender
- Godot 4.6.1 and matching export templates
- FFmpeg and FFprobe
- OpenJDK 17
- Android command-line tools, platform-tools (ADB), Android API 35 and build-tools 35.0.0

The image pins release versions and verifies downloaded Godot and Android command-line tool archives with SHA-256 checksums. The managed process runs as an unprivileged Linux user. No user needs to clone the Foundry repository, install Python, or run terminal commands to use the hosted toolchain.

This is a separate private service, not the public RevelaCode Flask backend and not the paired-PC Local Agent.

## Provisioning in Render

1. Create a private Render service from this repository using [the managed-compute Blueprint](render.nexora-compute.yaml). It uses the `4c-16g` private-service plan (4 CPU / 16 GB RAM). This is a paid, always-on compute allocation; confirm the plan and expected spend in Render before syncing the Blueprint.
2. Before the image can install Android SDK packages, the NEXORA operator must review the current Android SDK licence terms and accept them on behalf of the organisation. Only after that acceptance, set the GitHub repository variable `NEXORA_ANDROID_SDK_LICENSES_ACCEPTED=true`. The Docker build deliberately fails closed while this variable is unset; it does not silently accept licence terms during an unattended build.
3. Set `NEXORA_MANAGED_COMPUTE_SECRET` to a strong secret on the private service.
4. In the existing `nexora-foundry-api` control-plane service, add:
   - `NEXORA_MANAGED_COMPUTE_URL=http://nexora-managed-compute:10000`
   - `NEXORA_MANAGED_COMPUTE_SECRET` with the same secret as the private worker
   - `NEXORA_MANAGED_COMPUTE_ALLOW_HTTP=true` only when both services are on Render's private network in the same region
5. Do not expose port 10000 publicly. The worker accepts internal requests authenticated with the server-side secret. It never receives the signed-in user's NEXORA access token.
6. Confirm the private worker `/health` reports `toolchain_ready=true` and that `/api/compute/capabilities` on the signed-in Foundry control plane reports the same.

The Blueprint deliberately does not rewrite or replace the existing RevelaCode API, account database, authentication or the creator's Local Agent.

## Workload placement

`services/worker/workload_planner.py` compares the paired computer's current available CPU cores, total and available RAM, free storage, required tools, Android SDK readiness and supported GPU memory against the managed worker's measured container quota and installed tools.

- Light workspace editing stays on the creator device when it has safe headroom.
- Procedural 3D, movie processing and Android export can be planned for the managed worker when the user computer lacks required tools or resources and the worker passes preflight.
- Heavy 3D rendering is not assigned to the baseline 4-CPU/16-GB worker; it requires a separate higher-capacity worker.
- GPU image-to-3D is not advertised as ready without a managed GPU worker with a supported NVIDIA CUDA GPU and enough free VRAM.
- Physical Android USB/wireless device testing remains on the paired computer because a private Render worker cannot access the user's attached phone.

Hardware metrics are shared only after the user explicitly approves the Device Lab consent. The account API sends an allowlisted summary: CPU count/load/headroom, RAM totals/available, free disk, tool availability, Android SDK readiness and GPU memory. Local file paths, machine names, usernames, Android serials, project metadata and source files are not included in that request.

## Important execution boundary

This first managed-runtime stage provisions and verifies the server toolchain, exposes private capabilities, and returns a workload-placement recommendation. **It does not yet execute remote jobs, upload project/source files, or deliver remote build artifacts.** `job_submission_enabled` remains `false` intentionally.

A production job queue, durable project/object storage, explicit per-job remote-transfer approval, artifact download/retention policy, job ownership checks, cancellation and restart recovery must be completed before the UI may describe managed-server jobs as running. Until then, a managed-server placement is a candidate/preflight only; local jobs continue to use the paired Local Agent under its Device Access Bond and per-workload checks.

The managed worker's workspace root is `/var/data/nexora-compute`, backed by a 50-GB Render persistent disk mounted at `/var/data`. The runtime reports separately whether that mount is actually present and writable. A local Docker CI smoke run can report the toolchain ready while reporting workspace persistence unavailable; the Render deployment must show both before it can accept any customer workspace.

Render persistent disks are attached to one service instance only and prevent horizontal scaling and zero-downtime deploys. The managed compute worker is therefore deliberately configured as one instance. The disk is a persistent workspace volume, not a substitute for backups or a multi-region object store. Remote job submission remains disabled until the durable queue, upload/transfer approval, artifact retention and recovery workflow is implemented.

## Toolchain and resource verification

GitHub Actions builds the Docker image, starts the container, confirms every installed tool and SDK is visible to the runtime, and exercises the private capability endpoint. The workflow does not deploy a service or create any paid Render resource; provisioning happens only when an administrator syncs the Render Blueprint.

The CPU and RAM reported by the managed runtime are cgroup-limited container capacity, not the physical host's total resources. The placement planner uses the smaller container quota, not the Render host's full hardware.
