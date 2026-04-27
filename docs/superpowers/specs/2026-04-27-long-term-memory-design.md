# Long-Term Memory Phase 1 Design

## Goal

Build a first usable version of long-term memory for the chat app without adding embedding or pgvector yet.

The business goal is to let the assistant remember durable user preferences and project facts across conversations, while keeping the system easy to inspect, correct, and migrate. This phase should prove whether memory improves the chat experience before adding semantic vector search.

## Current State

The backend stores users, sessions, conversations, messages, and attachments with SQLAlchemy. Chat context currently comes from the latest `CONTEXT_WINDOW_SIZE` messages in the active conversation.

The app uses SQLite through `DATABASE_URL`. Schema changes are currently handled by `Base.metadata.create_all()` plus small manual `ALTER TABLE` checks in `init_db()`.

There is no durable user-level memory table, no migration history, and no memory management UI.

## Phase 1 Scope

Phase 1 includes:

- Move local development database configuration to PostgreSQL.
- Add Alembic so schema changes are versioned.
- Add a `memories` table for user-scoped long-term memory.
- Inject enabled memories into chat context before each model call.
- Save explicit, durable memories when the user asks the assistant to remember something.
- Add a simple UI path to view, disable, or delete memories.

Phase 1 excludes:

- Embedding models.
- pgvector similarity search.
- Automatic memory extraction from every conversation.
- Complex memory merging, conflict resolution, or scoring.

## Data Model

Add a `Memory` model backed by a `memories` table:

- `id`: string primary key.
- `user_id`: foreign key to `users.id`.
- `content`: durable memory text.
- `kind`: simple category such as `preference`, `project`, `tool`, or `fact`.
- `source_message_id`: optional foreign key to the user message that created it.
- `enabled`: boolean flag for whether the memory can be used.
- `created_at`: creation timestamp.
- `updated_at`: last update timestamp.
- `last_used_at`: optional timestamp updated when injected into chat context.

The table should be plain PostgreSQL-compatible SQLAlchemy. No vector column is added in this phase.

## Chat Flow

When a user sends a message:

1. Save the user message as the app does today.
2. Detect explicit memory intent with conservative rules, such as messages containing "记住", "以后你要记得", or "以后回答我时".
3. If the message has explicit memory intent, save a short memory record linked to the current user and source message.
4. Load recent conversation messages as short-term context.
5. Load enabled memories for the current user, ordered by recent use and creation time.
6. Add those memories to the model input as a system/context message before the recent conversation context.
7. Stream the assistant response and save it as today.

Memory injection should be limited to a small number of records so the prompt stays readable and inexpensive.

## API Surface

Add authenticated memory endpoints under `/api/memories`:

- `GET /api/memories`: list current user's memories.
- `POST /api/memories`: create a manual memory.
- `PUT /api/memories/{memory_id}`: update content, kind, or enabled state.
- `DELETE /api/memories/{memory_id}`: delete a memory.

All endpoints must require the current authenticated user and enforce user ownership.

## Frontend

Add a compact memory management entry in settings:

- Show whether long-term memory is available.
- List saved memories.
- Allow disabling or deleting a memory.
- Allow manually adding a memory.

The first version should be functional and restrained. It should not introduce a large new page unless the existing settings drawer becomes too crowded.

## Error Handling

If memory retrieval fails during chat, the chat request should still continue without long-term memory and log the failure on the backend.

If memory creation fails after the user message is saved, the chat request should still continue. The memory failure should not prevent the assistant from answering.

Database migration failures should fail startup or deployment loudly rather than being silently ignored.

## Testing

Backend tests should cover:

- Memory CRUD enforces user ownership.
- Explicit memory intent creates a memory.
- Non-explicit messages do not create memories.
- Enabled memories are injected into chat context.
- Disabled memories are not injected.

Existing memory context tests should continue to pass.

Frontend tests are not currently established in this project. Manual verification should cover creating, disabling, deleting, and seeing memory used in a follow-up chat.

## Future Phase

Phase 2 can add embedding and pgvector after Phase 1 validates memory behavior.

That later phase should add vector columns, embedding configuration, backfill existing memories, and retrieve only semantically relevant memories instead of injecting a small recent/enabled set.
