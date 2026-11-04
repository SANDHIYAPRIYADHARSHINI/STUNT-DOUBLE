# Architecture

```text
Task request -> Task registry -> Demo source -> Reset copies -> Mask
                                                        |
                        +-------------------------------+
                        v               v               v
                    SQLite A        SQLite B        SQLite C
                    Mock agent 1    Mock agent 2    Mock agent 3
                        |               |               |
                        +------------ row diffs --------+
                                        |
                              Consensus comparison
                                        |
                         Risk score + injection flags
                                        |
                             Human review decision
                                        |
                              Approval gate checked
                                        |
                          Apply DISABLED / rollback NO-OP
```

## Data flow

The API stores task metadata in memory. `create_demo_database` seeds an owned on-disk demo source with three fake customers. `create_sandbox_databases` uses read-only source connections and SQLite backup to create three independent files. `reset_sandboxes` restores them from that source before each rehearsal. The runner masks sensitive fields in each copy before agent snapshots, then commits mock changes to the copies. The demo source remains unchanged during rehearsals and resets. `DATABASE_URL` is reserved for production and never opened; `DEMO_SOURCE_DATABASE_URL` is a separate synthetic-only source.

For a request containing `delete` and `inactive`, the first two mock planners return `DELETE FROM customers WHERE status = 'inactive'`; the third returns `DELETE FROM customers` to demonstrate an overbroad change. User text never becomes SQL. Unsupported requests are explicitly skipped. The mocks do not represent general natural-language understanding. Before/after snapshots capture inserts, updates and deletes with stable primary keys. Full masked preimages and postimages remain available in the run record while sandbox files persist until the next reset.

## Isolation

Three SQLite-backed volumes separate sandbox storage. Every agent uses its own persistent file. A process-level reentrant lock serializes reset and rehearsal; multiple API workers, concurrent CLI resets and external writers are unsupported. All paths must be distinct, including symlink/hard-link aliases, and must not alias the reserved production path. Existing files must carry the demo application ID before reset can overwrite them. Reset restores schema as well as rows; the three backups run sequentially and are not an atomic multi-file transaction. The API is the only process in this scaffold; these are not container-per-agent security boundaries. TODO: Vultr workers with restricted filesystem, network, resources and hard execution deadlines before real LLM-generated SQL is permitted. Current timeout is SQLite lock wait only.

## Diffing

The engine consumes three uniquely identified `RunResult` objects for the same task. Final net changes group by table and primary key, then by operation and material values. Inserts compare postimages, deletes compare preimages, and updates compare changed-field before/after values (including field presence). Unchanged columns are excluded from update signatures. Duplicate observations from one agent do not add votes.

All three matching observations are unanimous. Exactly two matching observations with no competing variant are partial agreement. Multiple material variants for a row are conflicting, including delete-versus-update; this classification takes precedence over majority agreement. A unilateral change is a scope conflict. The default demo therefore has one unanimous deletion and two additional scope conflicts from agent 3.

Each classified entry preserves row images and adds supporting agent IDs, unchanged/unavailable agent IDs, changed fields, a reason, and competing observations. Failed/skipped agents are unavailable rather than unchanged votes. Warnings mark incomplete observations. No variant is designated correct.

Per-agent affected counts deduplicate row identities from committed net changes and statement observations. Maximum count is the largest per-agent value; blast radius is their union, including transient changes and excluding rollbacks. Legacy affected_row_count remains the union of net-change rows. Risk analysis consumes the blast-radius estimate. In the demo the counts are 1/1/3, maximum 3 and blast radius 3.

## Risk

Unbounded DELETE/UPDATE and schema-destructive SQL score critical. Affected rows above the configured limit, disagreement and suspicious instruction patterns increase the score. Reports include level, numeric score, warnings, blast radius and suspected injection flags. These heuristics are advisory and are not a SQL parser, execution policy, or reliable security classifier. TODO: Gemma-assisted signals with deterministic enforcement and structured audit storage.

## Approval and rollback

A reviewer explicitly approves or rejects a particular run. Apply rejects missing/rejected decisions even if the environment says approval is optional. Approved apply returns a disabled status; rollback returns a no-op status. Neither connects to a production database. Audit events record decisions and attempted apply/rollback calls in memory. This is an audit stub, not a durable rollback implementation.

Before enabling a production adapter: authenticate reviewers; persist immutable run digests and decisions; reject stale approvals; enforce policies and affected-row limits; verify source preconditions; atomically apply only approved changes; capture transactional inverse changes; and test rollback conflicts. Production writes remain out of scope for this scaffold.

## API and storage boundaries

Routers expose health, tasks, sandbox runs, diffs, risk and approval. Pydantic validates requests and serializes responses. SQLAlchemy parses connection URLs; SQLite handles rehearsal tables. Metadata uses a locked process-local store and is lost on restart, so only a single API worker is supported. Production deployments need durable SQLModel/SQLAlchemy metadata tables, access control and a job queue.

## Rehearsal provider and observation contracts

`RehearsalAgent.plan` accepts the same task for each provider and returns an `AgentPlan` with SQL operations and raw output. The default `get_agents` dependency builds two cautious mock agents and one deliberately dangerous mock; Python callers may inject three providers directly. Future Gemma adapters implement this contract without handling connections. Execution is sequential on independent reset copies.

The runner opens only each provider's assigned sandbox, masks the baseline, and begins a transaction. A SQLite authorizer restricts SQL to customer DML and reads; ATTACH, metadata access, functions, transaction statements and schema changes are denied. TODO: replace the local executor with restricted Vultr workers and hard timeouts for real LLM plans.

Snapshots around every statement yield operation-level row observations. A `RunResult` records stable agent identity, unique execution identity, task ID, attempted SQL, execution status, raw response, inserted/updated/deleted rows and distinct affected count. A separate final net diff feeds consensus. This preserves transient row changes in the statement log while avoiding false conflicts from intermediate versions of one row.

Each agent transaction either commits or rolls back. On failure, earlier statement observations are retained with `rolled_back` status, the failing statement carries an error, and committed changes are empty. Provider exceptions also become failed results rather than stopping the remaining agents. Any failed provider marks the rehearsal failed and adds a critical incomplete-observation warning. POST returns all three results synchronously; GET returns their stored representation. The source and production database remain untouched.
