# OLO Knowledge — fresh-install memory and RAG

`olo-memory` and `olo-rag` are separate Java 21 processes, databases, credentials, TLS identities and deployments.
Only ToolGate Tool Hosts may call them. OLO backend/workers use the Gateway, never these listeners or databases.
There is no import, migration, legacy reader, anonymous mode or long-term user-memory endpoint.

## Build and qualify

Build/publish the sibling ToolGate SDK with `publishJavaSdkLocally` and its contracts with
`:contracts-java:publishMavenJavaPublicationToContractProofRepository -PcontractsPublicationVersion=0.10.0-dev`.
Then run Gradle 8.12 `:olo-memory:installDist :olo-rag:installDist` here. Build the two Java SDK packages in
`packages/` with Gradle 9.7.1 `build toolgatePackage`. Each declares the exact permission and root resource;
the executor broker adds the permit and client certificate. Packages never see database credentials or signing keys.

`python tools/test_services.py --with-vectors --with-tls` owns disposable PostgreSQL 16, Qdrant and Ollama containers,
downloads/caches the small `all-minilm:latest` evaluation artifact under ignored `build/`, and removes its containers.
It exercises forced PostgreSQL RLS under a non-owner/non-superuser role, two tenants/users, concurrent appends,
idempotency, ACL changes, publication/deletion races, real embeddings, real filtered vector queries and citations.
Without `--with-vectors`, the real-dependency test is explicitly skipped. Test doubles are identified in test comments.
These checks do not claim the M8/M10 corpus-quality, 5 MB freshness or 50-user latency targets are met.

## Trust and deployment contract

Apply `deploy/common.sql` plus `deploy/memory.sql` to an **empty memory database**; apply common plus `rag.sql`
to a **different empty RAG database**. The schema owner runs DDL. Separate application roles get only schema USAGE
and table SELECT/INSERT/UPDATE/DELETE; no schema ownership, SUPERUSER, BYPASSRLS or DDL. FORCE RLS uses the
transaction-local tenant setting. SQL also supplies tenant and resource predicates. A tenant-bound deployment and
Control service credential are required per tenant; a caller cannot select another tenant's credential or trust roots.

Both processes require `TENANT_ID`, `DATABASE_URL` (production: PostgreSQL TLS verify-full), `DATABASE_USER`,
`DATABASE_PASSWORD`, `TLS_KEYSTORE`, `TLS_TRUSTSTORE`, `TLS_STORE_PASSWORD`, `CONTROL_ORIGIN` (HTTPS),
`CONTROL_ISSUER`, `CONTROL_CREDENTIAL_FILE`. TLS stores are PKCS12. Port defaults to 8443.
The service truststore trusts only the executor client CA and Control server CA. Client certificates are mandatory;
no forwarded identity header is trusted. Mount credentials and stores read-only; rotate the Control JWT file atomically.

RAG additionally requires `QDRANT_ORIGIN`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`, `EMBEDDING_ORIGIN`,
`EMBEDDING_MODEL`, `EMBEDDING_DIGEST` (`sha256:<64 hex>`). Provision the Qdrant collection with cosine distance
and the model's actual dimension; index keyword payloads `tenant`, `kb`, `model`, `docVersion`. Install the model
before starting the service. Its digest is checked before/after embedding batches. A changed artifact fails closed.
Reindex through governed `rag.update` with `{type:"reindex",docId:"<uuid>"}`. The service loads the current
source/version inside its authorized transaction; scheduled payloads contain references only. Publication is atomic. Never mutate a model tag in place while serving traffic. A dedicated embedding process has no outbound
network after provisioning. The parser accepts only bounded UTF-8 text/plain and text/markdown, never URLs,
archives, HTML execution, embedded objects or filesystem paths.

Apply `deploy/network-policy.yaml` with a CNI that enforces policies. Deploy service Pods with labels
`app.kubernetes.io/part-of=olo-knowledge` and `app.kubernetes.io/name=olo-memory` or `olo-rag`.
Place database/Qdrant/embedding Pods in that namespace with the policy's corresponding name labels.
Do not publish service ports outside the cluster. Expose ClusterIP 8443 to Tool Hosts only. Backend/worker Pods
are outside the allowed ingress selector. The manifest also limits store ingress to the owning service and denies store/embedding egress.
Set CPU/memory limits, a read-only root filesystem, non-root UID and a bounded writable `/tmp` volume.

## API and consistency

POST `/v1/memory.{read,append,delete,share,export}` or `/v1/rag.{query,ingest,update,delete,share}`.
The **exact** authorized body is `{conversationId,request}` or `{kbId,request}`; `request` is a JSON string.
The string envelope avoids SDK default/null transformations changing the authorized request fingerprint.
Identity fields inside it grant nothing; a second root ID in the envelope is rejected. The root is always the actual
opaque UUID used by storage. No agent actor may authorize platform data. SERVICE mode is limited to `rag.update`
and still needs a matching database membership plus the scoped ToolGate grant.

Memory message requests contain stable `messageId`, `turnId`, `role`, `content`, `dependencies` and `create`.
One conversation lock assigns total sequence order by transaction acquisition. Reusing an ID with different content
is a conflict. Only one final assistant/failure/cancellation outcome is allowed per turn. Late cleanup markers cannot
replace a recorded final result. Pending markers are removed when a final outcome is committed.
History with `beforeMessageId` excludes the accepted current message; context is bounded conservatively by UTF-8
bytes (therefore at most the token budget), without splitting records/chunks. Summaries are deterministic extracts
with source IDs, dependency sets and versions; appends/shares/deletes invalidate them. Working state uses
`type=working`, optimistic `expectedVersion`, at most 16 KiB and 1–86400 seconds TTL; expiry is checked on reads
and physical cleanup runs every minute. Only the root conversation lifecycle writes messages.

RAG ingest/update contains `docId`, `content`, `mediaType`, `expectedVersion`, optional `create` for an empty KB.
Document metadata/ACLs and published versions live in PostgreSQL; Qdrant holds only vectors and opaque metadata.
Queries filter by tenant, KB, model and authorized document versions, then join the SQL published version and recheck
ACLs before release. No result cache exists. Root row locks serialize publication, ACL change and delete.
Delete commits a permanent tombstone, clears content/chunks/ACL overrides and queues vector cleanup durably.
Cleanup retries every five seconds; failed cleanup cannot make deleted data searchable.

Sharing is owner-controlled. `member`, `write`, `remove` share the root. RAG additionally accepts `docId` and
`restricted` to narrow inheritance or explicitly share a document with a user outside KB membership. Both the
ToolGate root grant and service ACL must permit access. Source checks revalidate document existence and version.

Writes consume a single-use Control permit inside the transaction and check its 15-second deadline before commit.
A consumed permit plus a lost/failed storage response is **OUTCOME_UNKNOWN**: reconcile storage through a fresh authorized receipt read, never mint a new effect permit to blindly repeat a write.
Use `memory.read` or `rag.query` with `{type:"receipt",invocationId:"<ToolGate invocation>"}`. Receipts are
transactional and scoped to tenant, original subject and root resource. `COMMITTED` proves the write committed;
`NOT_FOUND` is inconclusive. Export receipts contain no exported content. Memory deletion erases prior receipts
for the conversation and records only its deletion acknowledgement. Reads refresh Control scope again
before release. Database statement/lock timeouts are bounded. Resource IDs are chosen before ToolGate authorization
by the trusted platform/API, since the grant must bind the same ID the service will create.

## Remaining qualification gates

The suite includes separate application JVMs with mTLS listeners, live PostgreSQL, live vectors/embeddings,
and an explicitly simulated authenticated Control server. Control's own bridge/TLS tests run in ToolGate.
These component checks do not replace one real ToolGate → broker → mTLS listener → database
application test, Kubernetes network-denial test, Temporal worker/backend deployment test, RAG target evaluation,
or operational recovery drills. Record actual evidence before counting those M6/M7 acceptance gates complete.

## Repeatable local staging qualification

On Windows with Docker Desktop (Linux containers), Java 21, Python 3.11+ with `cryptography`, kubectl,
and network access to the pinned official images:

```powershell
.\qualification.ps1 start
.\qualification.ps1 status
.\qualification.ps1 test -Python C:\path\to\python.exe
.\qualification.ps1 test -Python C:\path\to\python.exe -Evaluation
.\qualification.ps1 stop
```

`start` creates a dedicated two-node `olo-qualification` kind cluster with Calico. It verifies the official kind
binary checksum, pins the Kubernetes node image by digest, and isolates its kubeconfig under ignored
`build/qualification/runtime/`. It caps the control-plane at 2 CPUs/3 GiB and the worker at 4 CPUs/8 GiB.
An existing cluster without this workspace's ownership record is refused. It never selects the user's current Kubernetes context.

`test` verifies the committed NetworkPolicies with 22 real positive/negative TCP probes. Probe servers only
qualify CNI isolation; application mTLS and authorization have their own tests. `-Evaluation` additionally runs
the 200-document, 150-question authorized corpus against disposable real PostgreSQL/Qdrant/Ollama instances.
The versioned labelled fixture is `fixtures/rag-evaluation-v1.json`. Component latency is reported explicitly
and must not be represented as Gateway latency or a staging load-test result.

`test -FullStack` runs the separate current-source Control/Gateway/Tool Host/application qualification fixture.
Build the service distributions and both packages using the commands above first. Build its dedicated, owner-labelled ToolGate images with:

```powershell
python tools/build_qualification.py
# Or build while starting a new staging session:
.\qualification.ps1 start -BuildImages -Python C:\path\to\python.exe
```

The helper builds the sibling current-source ToolGate repository and labels both images for `stop` cleanup;
it refuses to overwrite unowned image tags. The full-chain fixture provisions
its own exact root grants, tenant-bound users and enrolled hosts, and uses separate application containers and
PostgreSQL databases. It uses an explicitly trusted test user-credential issuer; RFC 8693 token exchange and
Temporal pipeline recovery are separate gates. Its Gateway/Control loopback hop is a development fixture,
not an assertion of encrypted transport throughout a production deployment. Full authorization/ingest qualification is still in progress; startup and user ingress have passed.

**Cleanup:** `stop` interrupts recorded fixture processes and removes this workspace's test containers,
volumes, networks, probe images, the kind cluster, a newly downloaded session-owned node image, and private
runtime files (generated credentials, keys and kubeconfig). Sanitized reports and source code remain.
Existing images, services and clusters are not removed. If cleanup fails, the ownership record remains so
`stop` can be retried. Reports are under `build/qualification/`; they are intentionally outside Git.
Docker inventory errors fail cleanup explicitly; success requires a final check that no labelled test
containers, volumes, networks or images remain. Running `stop` again is safe. Downloaded build tools and
shared dependency/model caches remain available for subsequent test runs; they are not running services.

The October 24 component evaluation measured recall@5 1.00, precision@5 0.733, zero leakage and 750 correct
citations. Its p95 component query latency was 2213 ms, above the accepted latency target. These results do
not close M8.2a or the M10 50-user/50,000-document load gate.

For restoring a lost vector index from the retained SQL source, governed `rag.update` accepts
`{type:"reindex",docId:"<uuid>",force:true}`. This publishes a new version even for the same embedding artifact;
normal scheduled reindex remains a no-op when the artifact is unchanged. A tombstone still refuses rebuilding.
