# Local deployment handoff

Scope: public synthetic PitOpt demo only. The private checkout is tested separately and must not be uploaded to the public host. P1–P6 certify the documented software scope; bench economics/domain geotechnical acceptance and native desktop checks remain outside that scope.

1. Download the verified demo release archive and its SHA256SUMS file. Verify the archive checksum, extract it into a new release directory, and run `sha256sum -c SHA256SUMS` there. Keep the old installation and its service/nginx configuration intact.
2. On the configured deployment laptop, inspect the existing PitOpt service on the VPS: service name, ExecStart, user, working directory, virtualenv, root and proxy port. Use that observed configuration; the cloud task does not invent or replace it. Back up the active application/root and record a rollback command before changing the service's release path.
3. Transfer only the verified public release. In a new virtualenv, install its wheel with `pip install --constraint requirements-tested-py312.txt pitopt-0.4.0-py3-none-any.whl`. The constraints profile is tested on Linux/Python 3.12; do not assume it certifies another platform. Run `pip check`.
4. Start the candidate on an unused loopback port, with its extracted runtime root:
   `PITOPT_DEFAULT_PROJECT=porphyry_synthetic python -m pitopt ui --root runtime --port <candidate-port> --no-browser --demo --public-host pitopt.orebit.id`
   Inspect `/api/projects` and both `/api/results?project=<example_tin|porphyry_synthetic>&scenario=project`; require `freshness.status == current`, a nonempty schedule and finite NPV. Check actual browser summary, plan and 3D/design screens. Public `/api/run` and upload/create requests must remain disabled. Never start the full writable local app on the public proxy.
5. Promote the same candidate through the existing service/reverse-proxy deployment mechanism. Restart only the identified PitOpt service. Preserve unrelated services, TLS and nginx routing. Confirm public HTTPS result identity and static asset hashes against the release manifest, not just HTTP 200. Keep the previous release available for rollback.
6. Record deployed release SHA256, source commits, backup/rollback path, install time, health and public hash comparisons. Deployment is not green until this receipt exists. No deployment is performed from this cloud task.

Generated projects/data and outputs are git-ignored. A source-only pull does not include the demo runtime. To rebuild locally, check out the public branch, install dependencies, run `make example porphyry`, then use `scripts/package_demo_release.py` with a fresh wheel and that runtime root.
