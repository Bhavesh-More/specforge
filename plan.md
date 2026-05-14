# SpecForge Implementation Plan

## Current State

### Already Implemented (Frontend)
| Page | Status | Description |
|------|--------|-------------|
| `/templates` | ✅ | Template listing, upload, DAG visualization, run configuration |
| `/executions` | ✅ | Execution history, node-level status tracking, detailed output |
| `/knowledge` | ✅ | Knowledge graph browser (rule files, links, stats) |
| `/healing` | ✅ | Self-healing event review, approve/reject patches |
| `/settings` | ✅ | Ollama model selection, health monitoring |

### Already Implemented (Backend)
| Layer | Files | Description |
|-------|-------|-------------|
| Compiler | `src/compiler/`, `src/models/cognitive_template.py` | DAG builder, template registry, CTD |
| Executor | `src/executor/` | Atomic executor, context surgeon, schema validator, result weaver |
| Knowledge | `src/knowledge/` | Graph indexer, traverser, manager |
| Healing | `src/healing/` | Failure detector, rule patcher, teacher client |
| Symbolic | `src/symbolic/` | MCP client, tool registry |
| Reasoning | `src/reasoning/` | Adversarial triad, lookahead DAG, cognitive rollback, confidence gate |

---

## Pages to Implement

### 1. Dashboard Page (`/`)
**Current:** Redirects to `/templates`  
**Should be:** Main overview page

**Components:**
- Ollama health widget (inline in layout already)
- Quick stats: templates count, executions this week, healing events
- Recent executions list (last 5)
- Quick actions: upload template, create new template, view docs
- System status: GPU usage, memory, queue depth (if metrics available)

**Backend endpoints needed:**
- `GET /api/stats` — aggregate statistics
- `GET /api/executions/recent?limit=5` — recent runs

---

### 2. Template Designer Page (`/templates/design`)

**New page** — Create/edit Cognitive Templates visually

**Features:**
- Canvas-based DAG builder (drag nodes, connect edges)
- Node configuration panel:
  - Node ID, name, description
  - Node type: standard/symbolic/adversarial/lookahead/parallel
  - Focus prompt editor (system prompt, user template)
  - Output JSON Schema
  - Dependencies
  - Retry configuration
- Side-by-side preview: visual DAG → JSON preview
- Validation: detect cycles, missing dependencies, circular references
- Export: download `.ct.json` file
- Save to registry (POST to `/templates`)

**Components needed:**
- `TemplateDesigner.tsx` — main canvas + editor
- `NodeConfigPanel.tsx` — node properties editor
- `JsonPreview.tsx` — live JSON preview

**Backend endpoints needed:**
- `POST /api/templates` — create template
- `PUT /api/templates/:id` — update template
- `GET /api/templates/validate` — validate DAG structure

---

### 3. Rule Editor Page (`/knowledge/:filename`)

**Current:** `KnowledgePage.tsx` shows file list but textarea has no content loading  
**Should be:** Full Markdown editor with wiki-link support

**Features:**
- Markdown editor with live preview (split view)
- Wiki-link autocomplete: suggest `[[filename]]` from existing rules
- Link validation: highlight broken links
- File tree sidebar (recursive folder structure)
- Recent changes history (git-based or internal versioning)
- Save button with version bump option

**Components needed:**
- `RuleEditor.tsx` — main editor with split view
- `LinkAutoComplete.tsx` — wiki-link autocomplete dropdown
- `FileTree.tsx` — recursive folder/file tree

**Backend endpoints needed:**
- `GET /api/rules/:filename` — fetch rule content
- `PUT /api/rules/:filename` — save rule content
- `GET /api/rules?recursive=true` — list all rules with hierarchy
- `GET /api/rules/linked?filename=xxx` — find nodes that link to this rule

---

### 4. Execution Detail Page (`/executions/:runId`)

**Current:** `ExecutionDetailPanel` is a modal  
**Should be:** Dedicated route for deep linking, history

**Features:**
- Same detail panel content but as full page
- Timeline view: execution stages over time
- Node dependency heatmap (timing by dependency level)
- Export options: JSON output, Markdown report, state.md download
- Re-run from this execution state (restart from failed node)
- Compare with other runs (diff view)

**Components needed:**
- `ExecutionTimeline.tsx` — visual timeline of execution
- `NodeDependencyHeatmap.tsx` — timing visualization
- `CompareExecutionsModal.tsx` — side-by-side run comparison

**Backend endpoints needed:**
- `GET /api/executions/:id/state.md` — fetch state file content
- `GET /api/executions/:id/output.json` — fetch final output as JSON
- `GET /api/executions/:id/diff?against=:otherId` — compare two runs

---

### 5. Templates Registry Page (`/templates/registry`)

**New page** — Browse pre-built Cognitive Templates

**Features:**
- Template marketplace (searchable)
- Categories: bug-report, medical-intake, code-review, financial-disclosure, etc.
- Template details modal (same as current, but from registry)
- Install button: downloads template to local registry
- Version matrix: show all versions of a template
- Rating/reviews (optional, could be user comments in template metadata)

**Components needed:**
- `TemplateRegistry.tsx` — template listing with search/filter
- `TemplateCard.tsx` — card view with stats (downloads, last updated)

**Backend endpoints needed:**
- `GET /api/templates/registry?category=xxx&search=yyy` — browse templates
- `GET /api/templates/registry/:name/versions` — version history
- `POST /api/templates/registry/install` — install template from registry

---

### 6. Node Execution Simulator (`/debug/:templateId`)

**New page** — Test individual nodes without full execution

**Features:**
- Select node from template
- Input mock data
- Test execution (calls Ollama with node's focus prompt)
- View raw output, parsed output, validation result
- Visualize what context would be passed (bento box preview)
- Test different execution tiers (FAST/REPAIR/DEEP)

**Components needed:**
- `NodeSimulator.tsx` — node test interface
- `ContextPreview.tsx` — visualize bento box assembly
- `TierSelector.tsx` — select execution tier for test

**Backend endpoints needed:**
- `POST /api/templates/:id/debug/:nodeId` — test execute single node
- `GET /api/templates/:id/context/:nodeId` — preview bento box for node

---

### 7. Self-Healing Analytics Page (`/healing/analytics`)

**New page** — Deep dive into self-healing patterns

**Features:**
- Most failed nodes table (by count)
- Failure trend over time (line chart)
- Rule file patch frequency (bar chart)
- Teacher model usage stats
- Top failure patterns (cluster similar failures)
- Confidence score per node (based on healing history)

**Components needed:**
- `HealingAnalyticsDashboard.tsx` — charts/summary
- `FailedNodesTable.tsx` — nodes sorted by failure count
- `FailurePatternCluster.tsx` — cluster visualization

**Backend endpoints needed:**
- `GET /api/healing/analytics/failure-counts` — top failed nodes
- `GET /api/healing/analytics/trends?period=7d` — healing events over time
- `GET /api/healing/analytics/clusters` — cluster similar failures

---

### 8. Settings Advanced Page (`/settings/advanced`)

**Current:** Settings has basic Ollama config  
**Should add:** Advanced tuning options

**Features:**
- Token budget settings (context surge, graph traversal)
- Execution tier thresholds (tier 2 failure count, tier 3 thresholds)
- Cache settings (TTL, max size)
- Teacher model prompt engineering (system prompt override)
- GPU/memory limits for local inference
- Logging level & format

**Components needed:**
- `AdvancedConfigForm.tsx` — form for all advanced settings
- `TokenBudgetSlider.tsx` — visual token budget control
- `CacheSettings.tsx` — cache configuration

**Backend endpoints needed:**
- `GET /api/config/advanced` — fetch current advanced config
- `PUT /api/config/advanced` — update advanced config

---

## Architecture Pages (Documentation)

### 9. Documentation Hub (`/docs`)

**New page** — Inline documentation for SpecForge concepts

**Sections:**
- Cognitive Task Decomposition (CTD) methodology
- Bento Box micro-contexts
- Self-Healing Loop explained
- Knowledge Graph architecture
- Inference-Time Scaling (Lookahead DAG)
- Neuro-Symbolic Offloading
- Adversarial Triad pattern
- Confidence-Gated Execution tiers

**Components needed:**
- `DocsSidebar.tsx` — section navigation
- `DocPage.tsx` — content renderer (Markdown)
- `InteractiveExample.tsx` — embed live examples

**Backend endpoints needed:**
- `GET /api/docs/:section` — fetch docs content

---

## Technical Debt to Fix

| Issue | File | Fix |
|-------|------|-----|
| Missing import `Skeleton` | `TemplatesPage.tsx:95` | Add `import { Skeleton }` or inline |
| Missing import `Skeleton` | `ExecutionsPage.tsx:30` | Same |
| Missing import `Skeleton` | `HealingPage.tsx:33` | Same |
| Missing import `Skeleton` | `KnowledgePage.tsx:13` | Same |
| Unused import | `ExecutionDetailPanel.tsx:3` | Remove `Circle` icon if not used |
| No actual content loading | `KnowledgePage.tsx:93-96` | Load rule file content from API |
| No pagination | All lists | Add for 100+ items |
| No error boundary | App-wide | Add error boundaries |

---

## Priority Roadmap

| Phase | Pages | Timeline |
|-------|-------|----------|
| **1** (MVP) | Dashboard, Template Designer, Rule Editor | 2 weeks |
| **2** (Enhance) | Executions Page (dedicated), Template Registry | 1 week |
| **3** (Deep) | Node Simulator, Healing Analytics | 2 weeks |
| **4** ( docs) | Advanced Settings, Documentation Hub | 1 week |

---

## API Endpoints Summary

### New Endpoints Needed

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stats` | Aggregate statistics |
| GET | `/api/executions/recent` | Recent executions |
| POST | `/api/templates` | Create template |
| PUT | `/api/templates/:id` | Update template |
| GET | `/api/templates/validate` | Validate DAG |
| GET | `/api/templates/registry` | Browse template registry |
| POST | `/api/templates/registry/install` | Install template |
| POST | `/api/templates/:id/debug/:nodeId` | Test single node |
| GET | `/api/templates/:id/context/:nodeId` | Preview bento box |
| GET | `/api/healing/analytics/failure-counts` | Top failed nodes |
| GET | `/api/healing/analytics/trends` | Healing trends |
| GET | `/api/config/advanced` | Get advanced config |
| PUT | `/api/config/advanced` | Update advanced config |
| GET | `/api/docs/:section` | Documentation content |

### Existing Endpoints (Already Implemented)
- `GET /api/templates` — list templates
- `GET /api/templates/:id` — get template detail
- `POST /api/executions` — start execution
- `GET /api/executions` — list executions
- `GET /api/executions/:id` — get execution detail
- `GET /api/knowledge/files` — list rule files
- `GET /api/healing/events` — list healing events
- `PUT /api/healing/:id/approve` — approve healing
- `PUT /api/healing/:id/reject` — reject healing
- `GET /api/ollama/models` — list available models
- `GET /api/ollama/health` — check Ollama status
- `GET/PUT /api/models/selected` — get/set model selection

---

## Bug Fixes (Completed)

### Dashboard Page (`/`) - FIXED
| Issue | Fix |
|-------|-----|
| Templates count = 0 | Fixed path in `dashboard.py`: `Path(__file__).parent.parent.parent.parent` instead of `.parent.parent.parent` |
| Healing events = 4 | Changed to count from Redis `specforge:healing_events:index` instead of counting .md files in rules/ |
| Recent executions missing data | Backend `executions.py` already returns full data with template names |

### Healing Page (`/healing`) - FIXED
| Issue | Fix |
|-------|-----|
| No healing events shown | Migrated from in-memory `_events_store` to Redis storage with index key |
| Events not persisted | `SelfHealingOrchestrator` now stores events in Redis via `_store_event_in_redis()` |

### Knowledge Page (`/knowledge`) - FIXED
| Issue | Fix |
|-------|-----|
| No rule files shown | `list_rule_files()` now reads actual file content from disk |
| File not loading when selected | Added `value` prop and `onChange` to textarea, content loads from API response |

### Root Causes Resolved
1. **Dashboard path resolution** - Fixed to use 4 parents to reach project root from `src/api/routers/`
2. **Healing events storage** - Switched from in-memory dict to Redis with proper indexing
3. **Knowledge files content** - Added file read logic to API endpoint

---

## Known Issues (Remaining)

### Execution Page (`/executions`)
| Bug | Description | Impact |
|-----|-------------|--------|
| Clicking execution goes to blank page | No `/executions/:runId` route, only modal exists | No deep linking, can't history navigate |

### Priority: Low
- No template registry (`/templates/registry`)
- No execution detail page (`/executions/:runId`)
- No node execution simulator (`/debug/:templateId`)
- No healing analytics page (`/healing/analytics`)
- No advanced settings page (`/settings/advanced`)

---

## Notes

1. **State Management**: Using Zustand (`appStore.ts`) — track active runs, Ollama status
2. **Styling**: Tailwind CSS with custom theme tokens (`sf-green`, `sf-bg-deep`, etc.)
3. **Data Fetching**: React Query (`@tanstack/react-query`)
4. **Routing**: React Router v7
5. **DAG Visualization**: React Flow (`@xyflow/react`)
