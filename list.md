# SpecForge Implementation Checklist

## ✅ Done

### Frontend Pages
- [x] `/templates` - Template listing, upload, DAG visualization, run configuration
- [x] `/executions` - Execution history, node-level status tracking, detailed output
- [x] `/knowledge` - Knowledge graph browser (rule files, links, stats)
- [x] `/healing` - Self-healing event review, approve/reject patches
- [x] `/settings` - Ollama model selection, health monitoring

### Backend Layers
- [x] Compiler - DAG builder, template registry, CTD
- [x] Executor - Atomic executor, context surgeon, schema validator, result weaver
- [x] Knowledge - Graph indexer, traverser, manager
- [x] Healing - Failure detector, rule patcher, teacher client
- [x] Symbolic - MCP client, tool registry
- [x] Reasoning - Adversarial triad, lookahead DAG, cognitive rollback, confidence gate

---

## 🔴 Phase 1 (MVP) - Priority 1 - **IN PROGRESS**

### Dashboard Page (`/`) - **COMPLETE**
- [x] Create `DashboardPage.tsx` with:
  - [x] Quick stats widget (templates count, executions this week, healing events)
  - [x] Recent executions list (last 5)
  - [x] Quick actions (upload template, create new, view docs)
  - [x] System status (GPU, memory, queue depth)
- [x] Backend: `GET /api/stats` - aggregate statistics
- [x] Backend: `GET /api/executions/recent?limit=5` - recent runs

### Template Designer Page (`/templates/design`)
- [ ] Create `TemplateDesigner.tsx` - main canvas + editor
- [ ] Create `NodeConfigPanel.tsx` - node properties editor
- [ ] Create `JsonPreview.tsx` - live JSON preview
- [ ] Canvas-based DAG builder (drag nodes, connect edges)
- [ ] Node configuration (ID, name, type, focus prompt, output schema, dependencies, retry)
- [ ] Side-by-side preview (visual DAG → JSON)
- [ ] Validation (cycles, missing deps, circular refs)
- [ ] Export `.ct.json` file
- [ ] Save to registry (POST to `/templates`)
- [ ] Backend: `POST /api/templates` - create template
- [ ] Backend: `PUT /api/templates/:id` - update template
- [ ] Backend: `GET /api/templates/validate` - validate DAG

### Rule Editor Page (`/knowledge/:filename`)
- [ ] Create `RuleEditor.tsx` - main editor with split view
- [ ] Create `LinkAutoComplete.tsx` - wiki-link autocomplete
- [ ] Create `FileTree.tsx` - recursive folder/file tree
- [ ] Markdown editor with live preview
- [ ] Wiki-link autocomplete (`[[filename]]`)
- [ ] Link validation (highlight broken links)
- [ ] File tree sidebar
- [ ] Recent changes history
- [ ] Save button with version bump
- [ ] Backend: `GET /api/rules/:filename` - fetch rule content
- [ ] Backend: `PUT /api/rules/:filename` - save rule content
- [ ] Backend: `GET /api/rules?recursive=true` - list all rules
- [ ] Backend: `GET /api/rules/linked?filename=xxx` - find nodes linking to rule

---

## 🟡 Phase 2 (Enhance) - Priority 2

### Execution Detail Page (`/executions/:runId`)
- [ ] Create `ExecutionTimeline.tsx` - visual timeline
- [ ] Create `NodeDependencyHeatmap.tsx` - timing visualization
- [ ] Create `CompareExecutionsModal.tsx` - side-by-side comparison
- [ ] Dedicated route (full page, not modal)
- [ ] Timeline view of execution stages
- [ ] Node dependency heatmap
- [ ] Export options (JSON, Markdown, state.md)
- [ ] Re-run from failed node
- [ ] Compare with other runs
- [ ] Backend: `GET /api/executions/:id/state.md` - fetch state file
- [ ] Backend: `GET /api/executions/:id/output.json` - fetch output
- [ ] Backend: `GET /api/executions/:id/diff?against=:otherId` - compare runs

### Templates Registry Page (`/templates/registry`)
- [ ] Create `TemplateRegistry.tsx` - template listing with search/filter
- [ ] Create `TemplateCard.tsx` - card view with stats
- [ ] Template marketplace (searchable)
- [ ] Categories (bug-report, medical-intake, code-review, etc.)
- [ ] Template details modal
- [ ] Install button (download to local registry)
- [ ] Version matrix (all versions)
- [ ] Backend: `GET /api/templates/registry?category=xxx&search=yyy`
- [ ] Backend: `GET /api/templates/registry/:name/versions`
- [ ] Backend: `POST /api/templates/registry/install`

---

## 🟠 Phase 3 (Deep) - Priority 3

### Node Execution Simulator (`/debug/:templateId`)
- [ ] Create `NodeSimulator.tsx` - node test interface
- [ ] Create `ContextPreview.tsx` - bento box preview
- [ ] Create `TierSelector.tsx` - execution tier selector
- [ ] Select node from template
- [ ] Input mock data
- [ ] Test execution (Ollama with node's focus prompt)
- [ ] View raw/parsed output, validation result
- [ ] Context visualization (bento box)
- [ ] Test different tiers (FAST/REPAIR/DEEP)
- [ ] Backend: `POST /api/templates/:id/debug/:nodeId`
- [ ] Backend: `GET /api/templates/:id/context/:nodeId`

### Self-Healing Analytics Page (`/healing/analytics`)
- [ ] Create `HealingAnalyticsDashboard.tsx` - charts/summary
- [ ] Create `FailedNodesTable.tsx` - sorted by failure count
- [ ] Create `FailurePatternCluster.tsx` - cluster visualization
- [ ] Most failed nodes table
- [ ] Failure trend over time (line chart)
- [ ] Rule file patch frequency (bar chart)
- [ ] Teacher model usage stats
- [ ] Top failure patterns (cluster)
- [ ] Confidence score per node
- [ ] Backend: `GET /api/healing/analytics/failure-counts`
- [ ] Backend: `GET /api/healing/analytics/trends?period=7d`
- [ ] Backend: `GET /api/healing/analytics/clusters`

---

## 🟢 Phase 4 (Docs) - Priority 4

### Advanced Settings Page (`/settings/advanced`)
- [ ] Create `AdvancedConfigForm.tsx` - form for advanced settings
- [ ] Create `TokenBudgetSlider.tsx` - visual token budget control
- [ ] Create `CacheSettings.tsx` - cache configuration
- [ ] Token budget settings
- [ ] Execution tier thresholds
- [ ] Cache settings (TTL, max size)
- [ ] Teacher model prompt engineering
- [ ] GPU/memory limits
- [ ] Logging level & format
- [ ] Backend: `GET /api/config/advanced`
- [ ] Backend: `PUT /api/config/advanced`

### Documentation Hub (`/docs`)
- [ ] Create `DocsSidebar.tsx` - section navigation
- [ ] Create `DocPage.tsx` - content renderer (Markdown)
- [ ] Create `InteractiveExample.tsx` - embed live examples
- [ ] Cognitive Task Decomposition (CTD)
- [ ] Bento Box micro-contexts
- [ ] Self-Healing Loop
- [ ] Knowledge Graph architecture
- [ ] Inference-Time Scaling (Lookahead DAG)
- [ ] Neuro-Symbolic Offloading
- [ ] Adversarial Triad pattern
- [ ] Confidence-Gated Execution tiers
- [ ] Backend: `GET /api/docs/:section`

---

## ⚠️ Technical Debt

- [ ] Add missing `Skeleton` import to `TemplatesPage.tsx:95`
- [ ] Add missing `Skeleton` import to `ExecutionsPage.tsx:30`
- [ ] Add missing `Skeleton` import to `HealingPage.tsx:33`
- [ ] Add missing `Skeleton` import to `KnowledgePage.tsx:13`
- [ ] Remove unused `Circle` import from `ExecutionDetailPanel.tsx:3`
- [ ] Load rule file content from API in `KnowledgePage.tsx:93-96`
- [ ] Add pagination to all lists (100+ items)
- [ ] Add error boundaries app-wide

---

## 📊 Progress Summary

| Phase | Status | %
|-------|--------|---|
| Done | ✅ | 100% (Backend + Existing Pages) |
| Phase 1 | 🔴 | 0% |
| Phase 2 | 🟡 | 0% |
| Phase 3 | 🟠 | 0% |
| Phase 4 | 🟢 | 0% |
| Technical Debt | ⚠️ | 0% |
