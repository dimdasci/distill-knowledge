# C4 Abstractions — Reference

Load when identifying what things *are* in the architecture before drawing.

---

## The Four Abstractions

```
Person → uses → Software System → contains → Container → contains → Component → implemented by → Code
```

### Software System

The highest level. Delivers value to users. What a **single team** owns, builds, and can see inside.

**Heuristic:** code lives in one repo (or a set of repos the team owns); anyone on the team can modify it; team boundary ≈ system boundary.

**Not software systems:** product domains, bounded contexts, business capabilities, tribes, squads — these are organizational constructs, not abstractions.

### Container

An **application or data store** that must be running for the system to work. A **runtime boundary** around executing code or stored data.

Examples: server-side web app (Spring Boot, Node.js), SPA (React in browser), mobile app, serverless function (Lambda), database schema, blob store (S3), file system.

**Not Docker** — though there is often a one-to-one mapping.

**Web app — one or two containers?** Server-rendered HTML = one. Significant client-side JS (SPA) = two (server API + client app).

### Component

A grouping of related functionality behind a **well-defined interface**, running inside a container. **Not separately deployable.** All components share the container's process space.

By language:
- Java/C#: classes + interfaces
- JavaScript: module (objects + functions)
- Go: package
- Functional: module (functions, types)

### Code

Classes, interfaces, functions, enums — language primitives. Usually not worth diagramming manually; auto-generate if needed.

---

## Decision: Microservices

The key question: **who owns it?**

| Ownership | Model as |
|---|---|
| Same team owns all services | Each service = **container** (or group of containers) inside one software system |
| Different teams | Each team's services = separate **software system** |

**Common mistake:** modeling a microservice as a container and its API + database as *components*. Wrong — components are not deployable. The API is a container; the database is a container. The microservice is a *grouping* of containers.

### Worked example

1. *One team, monolith* → one software system, one container (the app), one database container.
2. *One team, microservices* → same system context. Container diagram shows individual service containers (API + DB pairs), grouped with color or dashed subgraphs.
3. *Multiple teams* → each team gets its own software system. Your context diagram shows the other team's system as an external system.

**Rule:** only show containers inside your own system boundary. Cross-team container diagrams encode coupling that shouldn't be there.

---

## Decision: Queues and Topics

**Wrong:** model the message bus (RabbitMQ, Kafka) as a single container → hub-and-spoke, obscures real coupling.

**Correct option 1 — explicit:** each queue/topic is its own container (a data store). Shows point-to-point coupling.

**Correct option 2 — implicit:** omit queue containers; put queue names on relationship arrows ("sends orders via OrderQueue"). Simpler but less explicit.

For pub/sub: producer publishes to topic; subscribers consume from it. Arrow direction follows data flow.

---

## Decision: Shared Libraries

**Wrong:** model as a container (libraries don't run).

**Correct:** at deployment there are *N copies* — one per container that uses it. Show the shared component inside each container. Use color coding to signal "this is shared code." Add a dashed boundary for the jar/package if helpful.

---

## Decision: Layers and Bounded Contexts

These are **organizational constructs**, not new abstractions. Show them as:
- Dashed `subgraph` boundaries inside a container
- Color coding
- Labels

The four C4 abstractions stay unchanged.

---

## Quick Reference

| I have... | It is a C4... | Because... |
|---|---|---|
| A whole product my team builds | Software System | Team boundary = system boundary |
| A Spring Boot app | Container | Deployable, running process |
| A React SPA | Container | Runs in browser, separate from API |
| A PostgreSQL database | Container | Running data store |
| An AWS Lambda function | Container | Deployable unit |
| A Spring Bean / service class | Component | Grouped functionality, not deployable alone |
| RabbitMQ (the broker) | Deployment detail | The individual queues are containers |
| A shared npm package | Component (copy per container) | Not a runtime thing on its own |
| "Our billing subsystem" | Organizational construct | Use a subgraph boundary |
| Another team's API | Software System (external) | You can't see inside it |
