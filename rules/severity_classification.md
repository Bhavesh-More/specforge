# Severity Classification

## Bug Severity Tiers

### Critical (SEV1)
**Trigger:** Data loss, security breach, complete system failure, or any bug causing irreversible harm.

Examples:
- Database transaction rollback on every request → permanent data loss
- Auth token secret hardcoded in git history → credential exposure
- Primary database connection pool exhaustion → 100% request failure

**Priority:** P0 — immediate response (< 1 hour)

### High (SEV2)
**Trigger:** Feature broken, significant degraded performance, or regression affecting core workflow.

Examples:
- Login fails for 30% of users → widespread auth breakage
- Search returns empty results for queries > 10 chars → core feature unusable
- Memory leak causing OOM restart every 2 hours → availability degradation

**Priority:** P1 — within 24 hours

### Medium (SEV3)
**Trigger:** UI glitch, non-blocking error, or cosmetic issue with workarounds available.

Examples:
- Button label typo on settings page → minor UX defect
- Error toast shows raw exception message → minor info leak
- Dark mode toggle flickers on load → cosmetic issue

**Priority:** P2 — within 1 week

### Low (SEV4)
**Trigger:** Warning, advisory, or pattern detected in logs without user-visible impact.

Examples:
- Repeated 404 for static asset → asset loading optimization opportunity
- Elevated latency on cache miss → performance tuning candidate
- Deprecated API usage warning in logs → future migration note

**Priority:** P3 — backlog

---

## ❌ What NOT to Do

**Misclassification Examples:**
- Marking "login button slightly misaligned" as Critical → wastes P0 resources
- Marking "user data deleted" as Medium → dangerously under-prioritized
- Marking "occasional tooltip delay" as High → disproportionate severity inflation
- Ignoring failed background jobs as Low when they affect nightly reporting → silent data loss

---

## ✅ Correct Classification Examples

| Bug | Severity | Why |
|-----|----------|-----|
| Payment webhook silently drops 5% of transactions | Critical | Money loss, undetectable without audit |
| File upload progress bar stuck at 99% but completes | Medium | Non-blocking cosmetic glitch |
| API returns 500 only on Tuesdays at midnight | High | Reproducible regression, affects core functionality |
| CSV export generates file 200ms slower than usual | Low | Performance advisory, no user impact |

---

[[python_rules]]
