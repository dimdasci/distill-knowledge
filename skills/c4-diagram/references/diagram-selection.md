# Diagram Type Selection — Reference

Load when choosing which diagram(s) to produce.

---

## Decision Matrix

| Question to ask | Answer points toward |
|---|---|
| Who reads this? Everyone | System Context or Landscape |
| Who reads this? Technical team | Container |
| Who reads this? Architects + devs | Component |
| What's the goal? Big picture / onboarding | System Context |
| What's the goal? Enterprise map | System Landscape |
| What's the goal? Technology choices visible | Container |
| What's the goal? Internal design of one app | Component |
| What's the goal? Show runtime behavior | Dynamic (sequence) |
| What's the goal? Show infrastructure mapping | Deployment |
| How many systems in scope? One | Context / Container / Component |
| How many systems in scope? Many | System Landscape |

---

## The Seven Diagram Types

### 1. System Context (C1)

| | |
|---|---|
| Scope | One software system |
| Shows | The system + surrounding people and external systems |
| Audience | Everyone |
| Recommended | **Yes — always** |
| Mermaid type | `flowchart TB` |

The most important diagram. Safe for non-technical stakeholders. No technology detail.

### 2. Container (C2)

| | |
|---|---|
| Scope | One software system (zoomed in) |
| Shows | Applications and data stores inside the system |
| Audience | Technical |
| Recommended | **Yes — always** |
| Mermaid type | `flowchart TB` with `subgraph` for system boundary |

Shows architecture shape, responsibility distribution, major technology choices, container communication. Does NOT show deployment (load balancers, replication).

### 3. Component (C3)

| | |
|---|---|
| Scope | One container |
| Shows | Components inside the container |
| Audience | Architects and developers |
| Recommended | Only if it adds value |
| Mermaid type | `flowchart TB` with `subgraph` for container boundary |

Consider auto-generating from code for long-lived documentation.

### 4. Code (C4)

| | |
|---|---|
| Scope | One component |
| Shows | Classes, interfaces, functions |
| Audience | Developers |
| Recommended | **No** — auto-generate only |
| Mermaid type | `classDiagram` |

Almost never worth manual creation.

### 5. System Landscape

| | |
|---|---|
| Scope | Enterprise / organisation / department |
| Shows | All people and software systems |
| Audience | Everyone |
| Recommended | Yes for larger organisations |
| Mermaid type | `flowchart TB` with `subgraph` for org boundary |

A context diagram without a focal system — the whole estate.

### 6. Dynamic

| | |
|---|---|
| Scope | A feature, story, or use case |
| Shows | Runtime interactions between elements |
| Audience | Technical and non-technical |
| Recommended | Sparingly — for complex interactions |
| Mermaid type | `sequenceDiagram` |

Shows *how* the system behaves at runtime for a specific scenario. Numbered interactions indicate ordering.

### 7. Deployment

| | |
|---|---|
| Scope | One or more systems in one environment |
| Shows | Where containers run (infra nodes, cloud services) |
| Audience | Technical (architects, ops, infra) |
| Recommended | **Yes** |
| Mermaid type | `flowchart TB` with nested `subgraph` for deployment nodes |

One diagram per environment (dev, staging, prod). Deployment nodes can nest: physical → VM → Docker → process.

---

## Practical Guidance

### "Most teams only need two"

System Context + Container diagrams cover 80% of communication needs. They are:
- Quick to create
- High-value
- Relatively stable (don't change with every feature)

Component and Code diagrams change with every PR. Create them only when the cost is justified.

### When to split

- Container diagram with > 15-20 services → split into per-service focused views (each service + immediate neighbors)
- System Landscape with > 20 systems → group by domain/department into sub-landscapes

### One static model → multiple views

The same system has:
- One context diagram (always)
- One container diagram (always)
- N component diagrams (one per container, if needed)
- N deployment diagrams (one per environment)
- N dynamic diagrams (one per interesting scenario)

All share the same abstractions and naming.
