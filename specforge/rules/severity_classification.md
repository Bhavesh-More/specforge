# Severity Classification Rules

Use these rules when classifying bug severity and priority. Accuracy matters — misclassification either inflates or deflates response urgency.

## Severity Levels

### Critical (SEV1)
Data loss, security breach, or complete system failure. No workaround exists.
- Production down, all users affected
- Database corruption or data exfiltration
- Authentication bypass allowing unauthorized access

Examples: `DELETE FROM users WHERE 1=1` in production query — all records deleted. Payment processing returns wrong amounts due to floating-point rounding.

### High (SEV2)
Major functionality broken, significant performance degradation, or serious regression. Temporary workaround may exist.
- Core feature unusable for all users
- Data integrity issues without total loss
- Security vulnerability with proven exploit path

Examples: Search returns empty results for all queries. Memory leak causes OOM crash after 2 hours under load.

### Medium (SEV3)
Partial functionality broken or degraded. Non-blocking issue with reasonable workaround available.
- UI glitch not affecting data integrity
- Performance degradation under specific conditions
- Secondary feature partially broken

Examples: Button text truncates on narrow screens. Export CSV includes BOM characters on non-UTF8 systems.

### Low (SEV4)
Advisory, warning, or cosmetic issue. No impact on functionality.
- Documentation errors
- Warning messages in logs with auto-recovery
- UI text inconsistencies

Examples: Deprecated API warning in logs. Tooltip text doesn't match button label.

## Priority Assignment

| Severity | Priority | Response SLA |
|----------|----------|--------------|
| Critical | P0 | Immediate (minutes) |
| High | P1 | Within 24 hours |
| Medium | P2 | Within 1 week |
| Low | P3 | Backlog |

## What NOT to Do

- **Don't classify as Critical just because it affects production.** A UI text truncation is High at most.
- **Don't use "SEV1 if user-facing, SEV2 otherwise."** Severity is about impact scope and data consequences, not visibility.
- **Don't assign P0 to every High severity bug.** P0 means drop everything and stop the bleeding.

## Correct Classification Examples

**Example 1 — Misclassified as Critical, correct is High:**
*Report:* "API returns 500 for /health endpoint"
*Wrong:* SEV1 / P0
*Right:* SEV2 / P1 (no data loss, health endpoint non-critical)

**Example 2 — Misclassified as Low, correct is High:**
*Report:* "Admin panel allows privilege escalation via crafted JSON payload"
*Wrong:* SEV4 (it's a "low priority feature")
*Right:* SEV1 / P0 (security vulnerability with confirmed exploit)

**Example 3 — Correct classification:**
*Report:* "Background job processor silently drops jobs when Redis connection resets"
*Classification:* SEV2 / P1 (data not lost, jobs are re-queued, workaround exists via manual re-trigger)

[[python_rules]]
