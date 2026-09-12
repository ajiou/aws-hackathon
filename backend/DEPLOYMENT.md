# Backend handoff to the infrastructure owner

The backend changes are restricted to `backend/`. The team's `infra/` template,
deployment scripts, shared requirements, and shared README remain unchanged.

## Build artifact

From `backend/`, with SAM CLI and Docker installed:

```bash
sam build --template-file template.yaml --use-container
```

The artifact in `.aws-sam/build/ApiFunction/` contains the `backend/` Python package
and its pinned Python 3.12 Linux dependencies. Its Lambda handler is
`backend.app.handler`. Building does not deploy anything.

## Integrating the existing stack

These are requested changes for the **infra owner**, not changes applied by this backend:

1. Build the existing `ApiFunction` using `backend/Makefile` (`BuildMethod: makefile`)
   with its existing `CodeUri: ../backend/`, or use the artifact described above.
2. Set the Lambda handler to `backend.app.handler`.
3. Package the **built** template/artifact. The original
   `aws cloudformation package` call on source files alone omits FastAPI, Pydantic's
   native module, and Mangum.
4. Keep the existing private bucket, read-only `serving/*` and `raw/pdf/*` S3
   permissions, CloudFront origin and query forwarding. CloudFront minimum API
   cache TTL must stay 0 so `no-store` responses are respected.
5. Keep `DATA_BUCKET` configured. A changed `DATA_REVISION` environment value
   recycles the process caches after a new serving snapshot is published.

The existing GET route can continue serving all nine API endpoints. An ANY route
is optional if unsupported methods should receive FastAPI's uniform 405 envelope.
The standalone `backend/template.yaml` offers an alternative API stack; it is not
required when the infra owner updates the existing function.

Deployment, live Lambda performance checks and frontend cutover remain with the
infra owner. No AWS resources have been deployed by these changes.
