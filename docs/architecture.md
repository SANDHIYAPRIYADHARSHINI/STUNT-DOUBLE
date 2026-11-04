# Architecture

```text
Task request -> Task registry -> Synthetic fixture -> Privacy shield
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

The API stores task metadata in memory. Sandbox execution creates a synthetic customer fixture in memory, masks common sensitive columns, and uses SQLite backup to create fresh file copies. Every agent gets a separate temporary directory under its configured sandbox volume. Copies are deleted on completion, including exceptions. Source/production databases are never opened, copied, or modified.

Only a fixed mock plan can run: a request containing `delete` and `inactive` executes a constant `DELETE FROM customers WHERE active = 0`. User text never becomes SQL. Other requests produce no changes. The mock does not represent general natural-language understanding. Before/after snapshots capture inserts, updates and deletes with stable primary keys. Full masked preimages and postimages remain available in the run record after temporary files are removed.

## Isolation

Three SQLite-backed volumes separate sandbox storage. Unique rehearsal directories prevent runs from sharing files. The API is the only process in this scaffold; these are not container-per-agent security boundaries. TODO: Vultr workers with restricted filesystem, network, resources and hard execution deadlines before real LLM-generated SQL is permitted. Current timeout is SQLite lock wait only.

## Diffing

Changes group by table and primary key. Identical before/after changes from all three agents are unanimous. Identical changes observed by fewer agents are partial agreement. Multiple variants for the same row are conflicting, even when two agents agree on one variant. Duplicate observations by one agent do not add votes. Blast radius counts distinct affected rows across all agents.

## Risk

Unbounded DELETE/UPDATE and schema-destructive SQL score critical. Affected rows above the configured limit, disagreement and suspicious instruction patterns increase the score. Reports include level, numeric score, warnings, blast radius and suspected injection flags. These heuristics are advisory and are not a SQL parser, execution policy, or reliable security classifier. TODO: Gemma-assisted signals with deterministic enforcement and structured audit storage.

## Approval and rollback

A reviewer explicitly approves or rejects a particular run. Apply rejects missing/rejected decisions even if the environment says approval is optional. Approved apply returns a disabled status; rollback returns a no-op status. Neither connects to a production database. Audit events record decisions and attempted apply/rollback calls in memory. This is an audit stub, not a durable rollback implementation.

Before enabling a production adapter: authenticate reviewers; persist immutable run digests and decisions; reject stale approvals; enforce policies and affected-row limits; verify source preconditions; atomically apply only approved changes; capture transactional inverse changes; and test rollback conflicts. Production writes remain out of scope for this scaffold.

## API and storage boundaries

Routers expose health, tasks, sandbox runs, diffs, risk and approval. Pydantic validates requests and serializes responses. SQLAlchemy parses connection URLs; SQLite handles rehearsal tables. Metadata uses a locked process-local store and is lost on restart, so only a single API worker is supported. Production deployments need durable SQLModel/SQLAlchemy metadata tables, access control and a job queue.
